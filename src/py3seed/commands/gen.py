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
from ..error import TemplateError
from ..utils import work_in, generate_names, parse_layout, iterate_layout

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

        :param fields - list of field name
        :param matcher - name|title|\w+_name
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


def _gen(s: str):
    """ Gen. """
    logger.info(f'Gen using {s}')
    # Seed file name has seed ext
    seed_file = f'{s}.sd'
    if not os.path.exists(seed_file):
        logger.error(f'Can not find seed file {seed_file}')
        return False
    # Out dir should be same with seed
    # e.g,
    #   www.sd -> www
    #   miniapp.sd -> miniapp
    output_path = s
    if not os.path.exists(output_path):
        logger.error(f'Can not find output path {output_path}')
        return False
    #
    # Parse seed file, which is in yaml format
    # e.g,
    # models:
    #   User:
    #     columns: avatar, name, status, roles, email, phone, create_time
    #     form: |-
    #       name
    #       phone
    #       intro
    #       avatar
    # blueprints:
    #   - name: dashboard
    #     views:
    #       - name: profile
    #         params: {extends: cust}
    #         layout: |-
    #           user.info, user.security
    #
    with open(seed_file) as stream:
        try:
            seed_content = yaml.safe_load(stream)
        except yaml.YAMLError as e:
            logger.error(f'Can not parse seed file {seed_file}, {e}')
            return False
    #
    # Parse .pyseed-includes in current folder.
    # e.g,
    #   www/static/assets
    #   www/static/js/enums.js.jinja2
    #   www/templates/seeds/{{#seeds}}.html.jinja2
    #   www/templates/{{#blueprints}}
    #   www/views/{{#blueprints}}.stub.py.jinja2
    #
    includes_file = '.pyseed-includes'
    includes = []
    logger.debug('pyseed includes:')
    with open(includes_file) as file:
        for line in file:
            line = line.strip()
            # skip comments and blank lines
            if line.startswith('#') or len(line) == 0:
                continue
            # only process the folders or files under output path
            if line.startswith(output_path):
                includes.append(line)
                logger.debug('  ' + line)
    if not includes:
        logger.error(f'Can not find any valid pyseed includes')
        return False
    #
    # Load all model's schema
    # 1. Find all the models definition in models package, please import all models in __init__.py
    # 2. Load model layouts from seed file
    # 3. Inject layouts to model schema
    #
    models, model_layouts = {}, {}
    module_name = 'models'
    module_spec = importlib.util.spec_from_file_location(module_name, os.path.join(output_path, module_name, '__init__.py'))
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    logger.info(f'Load models:')
    for attr in dir(module):
        attribute = getattr(module, attr)
        if inspect.isclass(attribute) and issubclass(attribute, BaseModel):
            logger.debug(f'  {attribute.__name__} with relations {list(attribute.__relations__.keys())}')
            # Layouts from seed file
            md = next((md for md in seed_content['models'] if md['name'] == attribute.__name__), {})
            md_layout = {
                'columns': [f.strip() for f in md.get('columns').split(',')] if 'columns' in md else None,
                'groups': [],
                'read': [],
                'form': [],
            }
            for k in md.keys():
                m = re.match(r'(group|read|form)\S*', k)
                if m:
                    md_layout[k] = parse_layout(md[k])[0]
                    # groups can be access by index in read/form layout, e.g, 0 means the first group
                    if m.group(1) == 'group':
                        md_layout['groups'].append(md_layout[k])
            # Keep class for further processing
            models[attribute.__name__] = attribute
            model_layouts[attribute.__name__] = md_layout
    # Inject layouts to model schema
    for md_name, md_class in models.items():
        models[md_name] = {'schema': md_class.schema(layouts=model_layouts), **generate_names(md_name)}
    #
    # Create context using seed content
    #
    context = {
        'models': models,  # {name: {names, schema}}}
        'blueprints': [],  # [blueprint]
        'seeds': [],
    }
    seed_set = set()
    logger.info(f'Seed file blueprints:')
    for bp in seed_content['blueprints']:  # Blueprints
        bp_name = bp['name']
        logger.info(f'{bp_name}/')
        blueprint = {'views': [], 'params': bp.get('params', {}), **generate_names(bp_name)}
        models_by_name = {}
        for v in bp['views']:  # Views
            v_name = v['name']
            logger.info(f'  {v_name}/')
            rows, seeds = parse_layout(v['layout'], models)
            for r in rows:
                rs = ', '.join(map(lambda x: x['name'], r))
                logger.info(f'    {rs}')
            #
            view = {'blueprint': blueprint, 'rows': rows, 'seeds': seeds, 'params': v.get('params', {}), **generate_names(v_name)}
            for seed in seeds:
                seed_name = seed['name']
                # Remove dulplicated seed at context level
                if seed_name not in seed_set:
                    context['seeds'].append(seed)
                    seed_set.add(seed_name)
                # Remove dulplicated model at blueprint level
                seed_model = seed['model']
                models_by_name[seed_model['name']] = seed_model
                # Add relation models
                for relation in seed_model['schema']['relations']:
                    models_by_name[relation] = models[relation]
            #
            blueprint['views'].append(view)
            blueprint['models'] = models_by_name.values()
        #
        context['blueprints'].append(blueprint)
    #
    # Do generation logic for each includes
    # NOTE: only files with jinja2 ext will be generated
    #
    env = _prepare_jinja2_env()
    logger.info(f'Generate template at {output_path}')
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
            # NOTE: do NOT render the seeds having suffix, e.g, product-read-1, block-read-feature-1
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
        "-s",
        nargs='?',
        metavar='seed',
        default='www',
        help="Specify the seed file name, default value is www. "
             "i.e, -s app means using seed file ./app.seed and models from ./app to generate files to ./app",
    )
    # TODO: support install/upgrade command
    parsed_args = parser.parse_args(args)
    return _gen(parsed_args.s)
