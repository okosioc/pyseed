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

from .. import registered_models
from ..error import TemplateError
from ..utils import work_in, generate_names, parse_layout

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

    env.globals['update_query'] = update_query
    env.globals['new_model'] = new_model
    env.globals['match_field'] = match_field
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
    #   app.sd -> app
    #   miniapp.sd -> miniapp
    output_path = s
    if not os.path.exists(output_path):
        os.mkdir(output_path)
    #
    # Parse seed file, which is in yaml format
    # e.g,
    # template: apple
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
            # TODO: Validate the seed content
        except yaml.YAMLError as e:
            logger.error(f'Can not parse seed file {seed_file}, {e}')
            return False
    #
    # Get template name from seed file, and then use .name/seed name as the template folder, as one template can support many platforms
    # e.g, app.sd using template apple -> .apple/app/
    #
    template_path = os.path.join('.' + seed_content['template'], s)
    if not os.path.exists(template_path):
        # TODO: Download template to the folder
        logger.error(f'Can not find template folder {template_path}')
        return False
    #
    # Import models package
    # 1. Find all the models definition in models package, please import all models in __init__.py
    #
    module_name = os.path.basename(output_path)
    module_spec = importlib.util.spec_from_file_location(module_name, os.path.join(output_path, '__init__.py'))
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    #
    # Load registered model schemas
    #
    models = {}
    for m in registered_models:
        models[m.__name__] = {'schema': m.schema(), **generate_names(m.__name__)}
    #
    logger.info(f'Found {len(models)} registered models: {list(models.keys())}')
    #
    # Create context using seed content
    #
    context = {
        'models': models,  # {name: {names, schema}}}
        'layouts': [],  # [layout]
        'blueprints': [],  # [blueprint]
        'seeds': [],
    }
    seed_set = set()
    logger.info(f'Seed file content:')
    for bp in seed_content['blueprints']:  # Blueprints
        bp_name = bp['name']
        logger.info(f'{bp_name}/')
        blueprint = {'views': [], **generate_names(bp_name)}
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
                # TODO: Replace old __relations__, so that we do not need to check very detail schema here
                for relation in seed_model['schema']['relations']:
                    relation_schema = seed_model['schema']['properties'][relation]
                    relation_model = relation_schema['items'] if relation_schema['type'] == 'array' else relation_schema
                    #
                    relation_model_name = relation_model['py_type']
                    models_by_name[relation_model_name] = models[relation_model_name]
            #
            blueprint['views'].append(view)
            blueprint['models'] = models_by_name.values()
        #
        context['blueprints'].append(blueprint)
    #
    # Do generation logic recursively
    #
    env = _prepare_jinja2_env()
    logger.info(f'Generate template {template_path} -> {output_path}')
    # Use depth-first to copy templates to output path, converting all the names and render in the meanwhile
    for d in os.listdir(template_path):
        _recursive_render(template_path, output_path, d, context, env)


def _recursive_render(t_base, o_base, name, context, env):
    """ Copy folder or file from template folder to output folder, handle names having list/varible syntax.

    Supported Syntax:
      {{#blueprints}}
      {{blueprint}}
      {{#views}}
      {{view}}
      {{#seeds}}
      {{seed}}
    """
    t_path = os.path.join(t_base, name)
    logger.debug(f'template {t_path}')
    t_name = ''.join(name.split())  # Remove all the whitespace chars from name
    out_names = []
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
            out_values = context['__blueprint']['views']  # Views under current blueprint
            out_names = [t_name.replace(syntax, v['name']) for v in out_values]
        elif key == 'seeds':
            out_key = '__seed'
            out_values = context['seeds']  # Seeds can be accessed at context level
            out_names = [t_name.replace(syntax, v['name']) for v in out_values]
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
            else:
                out_names = [t_name]
        else:
            out_names = [t_name]
    #
    # Copy & Render
    #
    if os.path.isdir(t_path):
        for i, o_name in enumerate(out_names):
            o_path = os.path.join(o_base, o_name)
            logger.debug(f'output {o_path}')
            if not os.path.exists(o_path):
                os.mkdir(o_path)
            # Can use this in sub folders and files
            if out_values:
                context[out_key] = out_values[i]
            # Copy the whole folder, use sorted() to make sure files starting with _ can be copied firtly
            for d in sorted(os.listdir(t_path)):
                _recursive_render(t_path, o_path, d, context, env)
            # Remove the files startswith #, which has been used for rendering
            for f in os.listdir(o_path):
                fp = os.path.join(o_path, f)
                if os.path.isfile(fp) and f.startswith('#'):
                    logger.debug(f'delete {f}')
                    os.remove(fp)
            #
            logger.debug(f'done {o_path}')
    #
    else:
        for o_name in out_names:
            o_path = os.path.join(o_base, o_name)
            logger.debug(f'copy {o_name}')
            shutil.copyfile(t_path, o_path)
            shutil.copymode(t_path, o_path)
        #
        # Render file
        # 1. Change working folder to ., so that jinja2 works ok
        # 2. Files with name starts with # will be include for rendering, so NO need to render
        # 3. Files with name ends with jinja2 will be render
        #
        o_base = os.path.abspath(o_base)
        with work_in(o_base):
            # Set jinja2's path
            env.loader = FileSystemLoader('.')
            o_context = {k: v for k, v in context.items() if not k.startswith('__')}
            #
            for i, o_name in enumerate(out_names):
                if o_name.startswith('#') or not o_name.endswith('.jinja2'):
                    continue
                #
                o_file = o_name.replace('.jinja2', '')
                logger.debug(f'render {o_file}')
                # Remove __ so that object can be accessed in template
                if out_values:
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
    parsed_args = parser.parse_args(args)
    return _gen(parsed_args.s)
