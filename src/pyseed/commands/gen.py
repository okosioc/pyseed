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
import json
import logging
import os
import re
import shutil
import sys
from typing import List

import inflection
from flask import request
from jinja2 import Environment, TemplateSyntaxError, FileSystemLoader
from werkzeug.urls import url_quote, url_encode

from pyseed import registered_models
from pyseed.error import TemplateError
from pyseed.utils import work_in

logger = logging.getLogger(__name__)


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
        return '{}?{}'.format(request.path, url_encode(args))

    env.globals['update_query'] = update_query

    #
    return env


def _gen(models_dir: str, seeds_dir: str, out_dir: str, template_names: List[str]):
    """ Gen. """
    logger.info(f'gen {models_dir} and {seeds_dir} to {out_dir}, using {template_names}')
    if not os.path.exists(models_dir):
        logger.error('No models folder')
        return False
    if not os.path.exists(seeds_dir):
        logger.error('No seeds folder')
        return False
    if not os.path.exists(out_dir):
        os.mkdir(out_dir)
    #
    # find templates from current folder
    # TODO: Download template to current working folder
    #
    working_folder = os.getcwd()
    logger.info(f'Working folder is {working_folder}')
    templates = []
    for g in os.listdir(working_folder):
        p = os.path.join(working_folder, g)
        if os.path.isdir(p) and g in template_names:
            templates.append(g)
    #
    if not templates:
        logger.error(f'Can not find any available templates by {template_names}')
        return False
    #
    # Import models package
    # 1. Find all the models definition in models package, please import all models in __init__.py
    #
    module_name = os.path.basename(models_dir)
    module_spec = importlib.util.spec_from_file_location(module_name, os.path.join(models_dir, '__init__.py'))
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    #
    # Load registered model schemas
    #
    models = {}
    for m in registered_models:
        models[m.__name__] = {'schema': m.schema(), **_generate_names(m.__name__)}
    logger.info(f'Found {len(models)} registered models: {list(models.keys())}')
    #
    # Create context using contents in seeds_dir
    # 1. Files in seeds_dir root folder are used as layouts
    # 2. Only contains one level sub folders and each folder will be generated to a blueprint
    # 3. Files in each blueprint folder will be genrated to views
    # 4. Each view file contains var lines, i.e. !key=value, and seed grids
    context = {
        'models': models,  # {name: {name, schema}}}
        'layouts': [],  # [layout]
        'blueprints': [],  # [blueprint]
        'seeds': [],
    }
    logger.info(f'Seeds:')
    for d in os.listdir(seeds_dir):  # Blueprints
        p = os.path.join(seeds_dir, d)
        if os.path.isdir(p):
            logger.info(f'{d}/')
            blueprint = {'views': [], **_generate_names(d)}
            models_by_name = {}
            for dd in os.listdir(p):  # Views
                view = {'blueprint': blueprint, 'rows': [], 'seeds': [], **_generate_names(dd)}
                pp = os.path.join(p, dd)
                logger.info(f'  {dd}')
                with open(pp) as f:  # Seeds defined in views
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        #
                        key_value_found = re.match('^!([a-zA-Z_]+)=(.+)$', line)
                        if key_value_found:
                            key, value = key_value_found.groups()
                            #
                            # NOTES:
                            # 1. Variables name should be in snake format, i.e, two_words
                            # 2. Variables can be accessed in templates, i.e, view.layout
                            #
                            value = _parse_varible_value(key, value)
                            view[key] = value
                        else:
                            row = {'columns': []}
                            if '|' in line:  # Nested column, e.g, a,b|c,d
                                for c in line.split('|'):
                                    column = []
                                    for cc in c.split(','):
                                        cc = cc.strip()
                                        seed = _parse_seed(cc, models)
                                        if 'model' in seed:
                                            models_by_name[seed['model']['name']] = seed['model']
                                            view['seeds'].append(seed)
                                            context['seeds'].append(seed)
                                        #
                                        column.append(seed)
                                    #
                                    row['columns'].append(column)
                            else:  # Single level column, e.g, a,b
                                for c in line.split(','):
                                    c = c.strip()
                                    seed = _parse_seed(c, models)
                                    if 'model' in seed:
                                        models_by_name[seed['model']['name']] = seed['model']
                                        view['seeds'].append(seed)
                                        context['seeds'].append(seed)
                                    #
                                    row['columns'].append(seed)
                            #
                            logger.info(f'    {line}')
                            view['rows'].append(row)
                #
                blueprint['views'].append(view)
                blueprint['models'] = models_by_name.values()
            #
            context['blueprints'].append(blueprint)
        else:
            logger.info(f'{d}')
            context['layouts'].append(d)
    #
    env = _prepare_jinja2_env()
    #
    # Iterate each template
    #
    for template in templates:
        #
        # Prepare paths
        #
        tempate_path = template
        output_path = out_dir
        if not os.path.exists(output_path):
            os.mkdir(output_path)
        logger.info(f'Generate template {template}: {tempate_path} -> {output_path}')
        #
        # Use depth-first to copy templates to output path, converting all the names and render in the meanwhile
        #
        for d in os.listdir(tempate_path):
            _recursive_render(tempate_path, output_path, d, context, env)


def _generate_names(name):
    """ Generate names. """
    name_wo_dot = name.replace('.', '-')  # e.g, plan.members-form -> plan-members-form
    return {
        'name': name,  # => SampleModel
        'name_lower': name.lower(),  # => samplemodel
        'name_kebab': inflection.dasherize(inflection.underscore(name_wo_dot)),  # => sample-model
        'name_camel': inflection.camelize(name_wo_dot, uppercase_first_letter=False),  # => sampleModel
        'name_snake': inflection.underscore(name_wo_dot),  # => sample_model
        'name_snake_plural': inflection.tableize(name_wo_dot),  # => sample_models
        'name_title': inflection.titleize(name_wo_dot),  # => Sample Model
    }


def _parse_varible_value(key, value):
    """ Parse value accordig to the key. """
    key = key.lower()
    value = value.strip()
    if key.startswith('has_') or key.startswith('is_'):
        if value.lower() in ['1', 'true', 'yes']:
            value = True
        else:
            value = False
    elif value.startswith('[') or value.startswith('{'):
        try:
            value = json.loads(value)
        except ValueError as e:
            logger.warning(f'Found invalid view varible {key}={value}')
    #
    return value


def _parse_seed(column, models):
    """ Parse column and return seed if any, e.g, post-query, post-read, user-form?is_horizontal=true.

    model-action?params
    """
    # params
    params = {}
    if '?' in column:
        column, query = column.split('?')
        for p in query.split('&'):
            key, value = p.split('=')
            params[key] = _parse_varible_value(key, value)
    # model-action
    tokens = column.split('-')
    name = tokens[0]
    sub = None
    # sub model, only support one level sub model
    if '.' in name:
        name, sub = name.split('.')
    # found model by name
    found = next((m for n, m in models.items() if n.lower() == name.lower()), None)
    if found:
        action = tokens[-1]
        return {'model': found, 'sub': sub, 'action': action, 'params': params, **_generate_names(column)}
    else:
        return {'params': params, **_generate_names(column)}


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
            out_values = context['__blueprint']['views']
            out_names = [t_name.replace(syntax, v['name']) for v in out_values]
        elif key == 'seeds':
            out_key = '__seed'
            out_values = context['seeds']
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
        # 2. Files with name starts with # will be include for rendering, so no need to render
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
        "-m",
        nargs='?',
        metavar='models',
        default='./models',
        help="Specify the models folder, default value is ./models",
    )
    parser.add_argument(
        "-s",
        nargs='?',
        metavar='seeds',
        default='./seeds',
        help="Specify the seeds folder, default value is ./seeds",
    )
    parser.add_argument(
        "-o",
        nargs='?',
        metavar='output',
        default='./grows',
        help="Specify the generation output folder, default value is ./grows",
    )
    parser.add_argument(
        "-t",
        nargs='+',
        metavar='templates',
        help="Specify the templates",
    )
    parsed_args = parser.parse_args(args)
    return _gen(parsed_args.m, parsed_args.s, parsed_args.o, parsed_args.t)
