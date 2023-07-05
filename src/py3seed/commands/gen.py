# -*- coding: utf-8 -*-
"""
    gen
    ~~~~~~~~~~~~~~

    Command gen.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/9/1
"""
import argparse
import importlib.util
import inspect
import logging
import os
import re
import shutil
import sys
from typing import List

import yaml
from flask import request
from jinja2 import Environment, TemplateSyntaxError, FileSystemLoader
from werkzeug.urls import url_quote, url_encode

from .. import registered_models, BaseModel
from ..error import TemplateError, LayoutError
from ..utils import work_in, generate_names, parse_layout1, iterate_layout, parse_layout

logger = logging.getLogger('pyseed')


def _prepare_jinja2_env():
    """ Prepare env for rendering jinja2 templates. """
    #
    # For more env setting, please refer to https://jinja.palletsprojects.com/en/3.0.x/api/#jinja2.Environment
    #   trim_blocks=True, the first newline after a block is removed (block, not variable tag!)
    #   lstrip_blocks=True, leading spaces and tabs are stripped from the start of a line to a block
    #   keep_trailing_newline=True, Preserve the trailing newline when rendering templates.
    #
    env = Environment(trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)

    def split(value, separator):
        """ Split a string. """
        return value.split(separator)

    def items(value):
        """ Return items of a dict. """
        return value.items()

    def keys(value):
        """ Return keys of a dict. """
        return value.keys()

    def quote(value):
        """ Add single quote to value if it is str, else return its __str__. """
        if isinstance(value, str):
            return '\'' + value + '\''
        else:
            return str(value)

    def basename(value):
        """ Return file name from a path. """
        return os.path.basename(value)

    def urlquote(value, charset='utf-8'):
        """ Url Quote. """
        return url_quote(value, charset)

    env.filters['split'] = split
    env.filters['items'] = items
    env.filters['keys'] = keys
    env.filters['quote'] = quote
    env.filters['basename'] = basename
    env.filters['urlquote'] = urlquote

    def update_query(**new_values):
        """ Update query. """
        args = request.args.copy()
        for key, value in new_values.items():
            args[key] = value
        return url_encode(args)

    def new_model(class_name):
        """ New a model by class name. """
        klass = globals()[class_name]
        return klass()

    def match_field(fields, matcher):
        """ Get the first matching field from columns.
        e.g,
        - match_field(columns, 'name|title|\\w+_name')
        """
        matcher = re.compile(matcher if matcher.startswith('(') else f'({matcher})')
        if isinstance(fields, dict):
            fields = fields.keys()
        #
        for f in fields:
            if matcher.match(f):
                return f
        # If no matching, return nothing
        return None

    def parse_layout_fields(schema, action):
        """ Parse layout fields.

        each column in layout can be blank('')/hyphen(-)/summary($)/group(number)/field(string)/inner fields(has children) suffixed with query and span string
        this function will return a list of field names.
        """
        return list(iterate_layout(schema[action], schema['groups']))

    env.globals['update_query'] = update_query
    env.globals['new_model'] = new_model
    env.globals['match_field'] = match_field
    env.globals['parse_layout_fields'] = parse_layout_fields
    #
    return env


def _gen(ms: str, ds: str):
    """ Gen. """
    logger.info(f'Gen for domain(s) {ms} under domain(s) {ds}')
    include_models = [m.strip() for m in ms.split(',')] if ms else []
    include_domains = [d.strip() for d in ds.split(',')] if ds else []
    # Domains should be project folders, i.e, [www, miniapp, android, ios, ...]
    for d in include_domains:
        if not os.path.exists(d):
            logger.error(f'Can not find domain {d}')
            return False
    #
    # Load all model's schema and views
    # 1. Find all the models definition in core.models package, please import all models in __init__.py
    # 2. Load each models' schema and views, filtering models and views that needs to be generated
    #
    model_settings = {}
    domain_names, view_names = set(), set()
    module_name = 'models'
    module_spec = importlib.util.spec_from_file_location(module_name, os.path.join('core', module_name, '__init__.py'))
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    logger.info(f'Load models:')
    for attr in dir(module):
        attribute = getattr(module, attr)
        if inspect.isclass(attribute) and issubclass(attribute, BaseModel):
            model_name, model_class = attribute.__name__, attribute
            logger.info(f'- {model_name}')
            # Parse model schema and views
            schema = model_class.schema()
            model_setting = {
                'schema': schema,  # dict
                **generate_names(model_name)
            }
            #
            views = []
            for k, v in model_class.__views__.items():
                # Filter views if include_domains has value
                domains = v['domains']
                if include_domains:
                    domains = [d for d in domains if d in include_domains]
                #
                if not domains:
                    continue
                else:
                    domain_names.update(domains)
                # Parse view name
                # e.g,
                # - index -> blueprint = public, name = index
                # - admin/dashboard -> blueprint = admin, name = dashboard
                if '/' in k:
                    blueprint, name = k.split('/')
                else:
                    blueprint = 'public'
                    name = k
                logger.info(f'    {blueprint}/{name}')
                # Validate to make sure view name is unique
                if name in view_names:
                    logger.error(f'View name {v["name"]} is not unique')
                    return False
                #
                view_names.add(name)
                #
                l = parse_layout(v['layout'], schema)
                views.append({
                    'model': model_setting,
                    'blueprint': blueprint,
                    'domains': domains,
                    'action': l['action'],
                    'params': l['params'],
                    'rows': l['rows'],
                    'layout': v['layout'],
                    **generate_names(name)
                })
            # Views may be empty if no views match
            if not views:
                continue
            #
            model_setting['views'] = views
            # Filter model if include_models has value
            if include_models and include_models.count(model_name) == 0:  # case-sensitive
                continue
            #
            model_settings[model_name] = model_setting
    #
    if not model_settings:
        logger.error('Can not find any models to gen')
        return False
    #
    # For each domain:
    # 1. Build context
    # 2. Render jinja2 templates
    #
    for domain in domain_names:
        # Domain should be a project folder, e.g, www/miniapp/android/ios
        logger.info(f'Gen for domain {domain}')
        #
        # Parse .pyseed-includes in current folder, files whose name ends with jinja2 and folders whose name contains syntax {{ should be included
        # e.g,
        #   www/static/js/enums.js.jinja2
        #   www/templates/{{#blueprints}}
        #   www/views/{{#blueprints}}.stub.py.jinja2
        #
        includes_file = '.pyseed-includes'
        includes = []
        logger.info('Includes:')
        with open(includes_file) as file:
            for line in file:
                line = line.strip()
                # skip comments and blank lines
                if line.startswith('#') or len(line) == 0:
                    continue
                # only process the folders or files under output path
                if line.startswith(domain):
                    includes.append(line)
                    logger.info('  ' + line)
        if not includes:
            logger.error(f'Can not find any valid includes')
            return False
        #
        # Build context
        #
        blueprints = []
        for model_name in model_settings.keys():
            model_setting = model_settings[model_name]
            # Filter views under this domain and init blueprints
            for v in model_setting['views']:
                if domain in v['domains']:
                    blueprint_name = v['blueprint']
                    blueprint = next((b for b in blueprints if b['name'] == blueprint_name), None)
                    if not blueprint:
                        blueprint = {'views': [], 'models': [], **generate_names(blueprint_name)}
                        blueprints.append(blueprint)
                    #
                    blueprint['views'].append(v)
        #
        logger.info(f'Blueprints:')
        for bp in blueprints:  # Blueprints
            bp_name = bp['name']
            logger.info(f'{bp_name}/')
            for v in bp['views']:  # Views
                v_name, v_layout = v['name'], v['layout']
                logger.info(f'  {v_name}: {v_layout}')
        #
        context = {
            'models': model_settings,
            'blueprints': blueprints,
        }
        #
        # Do generation logic for each includes
        #
        env = _prepare_jinja2_env()
        for include in includes:
            base = os.path.dirname(include)
            name = os.path.basename(include)
            _recursive_render(base, base, name, context, env)


def _recursive_render(t_base, o_base, name, context, env):
    """ Render output folder/file, handle names having list/varible syntax.

    Supported Syntax:
      {{#blueprints}}
      {{blueprint}}
      {{#views}}
      {{view}}
      {{#seeds}}
      {{seed}}
      {{#models}}
      {{model}}
    """
    t_path = os.path.join(t_base, name)
    t_name = ''.join(name.split())  # Remove all the whitespace chars from name
    out_names = [t_name]  # if no matched list or varible syntax, process directly
    out_key, out_values = None, []
    #
    # Check list syntax, i.e, {{#name}}
    # This syntax iterate over every item of the list; do not generate anything if empty list and false value
    #
    match_list = re.search('(\\{\\{#[a-zA-Z._]+\\}\\})', t_name)
    if match_list:
        syntax = match_list.group(1)  # => {{#views}}
        key = syntax[3:-2]  # => views
        if key == 'blueprints':
            out_key = '__blueprint'
            out_values = context['blueprints']
            out_names = [t_name.replace(syntax, v['name']) for v in out_values]
        elif key == 'views':
            out_key = '__view'
            out_values = context['__blueprint']['views']  # views under current blueprint
            out_names = [t_name.replace(syntax, v['name']) for v in out_values]
        elif key == 'seeds':
            out_key = '__seed'
            # seeds can be accessed at context level, which means it can be used in different views, there is another way to access seed, that is blueprint->view->seed, we often use it generate backend logic
            # NOTE: do NOT render the seeds having alphanumeric suffix, e.g, Block-read-features-basic, Block-read-shop-products-grid
            out_values = [s for s in context['seeds'] if not s.get('suffix')]
            out_names = [t_name.replace(syntax, v['name']) for v in out_values]
        elif key == 'models':
            out_key = '__model'
            # models can be accessed at context level, NOTE: models is dict, {name: {names, schema}}}, so we use values() here
            out_values = list(context['models'].values())
            # names of blueprints/views/seeds are kebab formats because them will be used in the url directly, while modal names are always in camel case because of PEP8
            out_names = [t_name.replace(syntax, v['name_kebab']) for v in out_values]
        else:
            raise TemplateError(f'Unsupported list syntax: {syntax}')
    else:
        #
        # Check varible syntax, i.e, {{name}}
        # This syntax return the value of the varible
        #
        match_variable = re.search('(\\{\\{[a-zA-Z._]+\\}\\})', t_name)
        if match_variable:
            syntax = match_list.group(1)
            key = syntax[2:-2]
            if key in ['blueprint', 'view', 'seed']:
                out_key == f'__{key}'
                out_values = [context[f'__{key}']]
                out_names = [t_name.replace(syntax, v['name']) for v in out_values]
            elif key in ['model']:
                out_key == f'__{key}'
                out_values = [context[f'__{key}']]
                out_names = [t_name.replace(syntax, v['name_kebab']) for v in out_values]
            else:
                raise TemplateError(f'Unsupported varible syntax: {syntax}')
    #
    # Render folder recursively
    #
    if os.path.isdir(t_path):
        for i, o_name in enumerate(out_names):
            # For dir name that has list or varible syntax
            # e.g,
            #   www/templates/{{#blueprints}}
            #     ->
            #     www/templates/public
            #     www/templates/dash
            #     www/templates/demo
            #     ...
            o_path = os.path.join(o_base, o_name)
            if not os.path.exists(o_path):
                os.mkdir(o_path)
            # Can use this context value in sub folders and files
            if out_values:
                context[out_key] = out_values[i]
            # Render recursively
            for d in sorted(os.listdir(t_path)):
                _recursive_render(t_path, o_path, d, context, env)
    #
    # Render file
    #
    else:
        # Only process jinja2 files
        if not t_name.endswith('.jinja2'):
            return
        # Overwrite with template file content firstly
        # TODO: Merge logic
        # e.g,
        #  1. Files that has list or varible syntax, regenerate each time; The jinjas generated should be removed after generation
        #  www/templates/seeds/{{#seeds}}.html.jinja2
        #    ->
        #    www/templates/seeds/User-form.html.jinja2
        #    www/templates/seeds/Project-read.html.jinja2
        #    ...
        #  2. Files that is just a jinja, no need to overwrite just render directly; The jinja file should NOT be removed after generation
        #  www/static/js/enums.js.jinja2
        for o_name in out_names:
            o_path = os.path.join(o_base, o_name)
            if out_key:
                shutil.copyfile(t_path, o_path)
                shutil.copymode(t_path, o_path)
        # Change working folder to ., so that jinja2 works ok
        o_base = os.path.abspath(o_base)
        with work_in(o_base):
            logger.debug(f'working at {o_base}')
            # Set jinja2's path
            env.loader = FileSystemLoader('.')
            o_context = {k: v for k, v in context.items() if not k.startswith('__')}
            #
            for i, o_name in enumerate(out_names):
                o_file = o_name.replace('.jinja2', '')
                logger.debug(f'render {o_file}')
                # Remove __ so that object can be accessed in template
                if out_key:
                    o_context[out_key[2:]] = out_values[i]
                #
                try:
                    tmpl = env.get_template(o_name)
                except TemplateSyntaxError as exception:
                    exception.translated = False
                    raise
                rendered = tmpl.render(**o_context)
                #
                with open(o_file, 'w', encoding='utf-8') as f:
                    f.write(rendered)
                # Remove template file
                if out_key:
                    os.remove(o_name)


def main(args: List[str]) -> bool:
    """ Main. """
    parser = argparse.ArgumentParser(prog="pyseed gen")
    parser.add_argument(
        '-m',
        nargs='?',
        metavar='models',
        default=None,
        help='Tells pyseed to generate action for specific models.'
             'e.g,'
             '-m User means generating all views for User model'
    )
    parser.add_argument(
        '-d',
        nargs='?',
        metavar='domains',
        default=None,
        help='Tells pyseed to generate action for specific domains.'
             'e.g,'
             '-d www means generating all models\' views under www domain'
             '-m User -d www means generating all views for User model under www domain'
    )
    parsed_args = parser.parse_args(args)
    return _gen(parsed_args.m, parsed_args.d)
