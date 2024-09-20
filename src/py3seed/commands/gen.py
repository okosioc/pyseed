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
import configparser
from typing import List

from flask import request
from jinja2 import Environment, TemplateSyntaxError, FileSystemLoader, filters
from werkzeug.urls import url_quote, url_encode

import py3seed.ext
from py3seed import registered_models, BaseModel, TemplateError, LayoutError
from py3seed.utils import work_in, generate_names, get_layout_fields, parse_layout
from py3seed.merge3 import Merge3

logger = logging.getLogger('pyseed')
INCLUDES_FOLDER = '__includes'


def _prepare_jinja2_env(properties):
    """ Prepare env for rendering jinja2 templates. """
    #
    # For more env setting, please refer to https://jinja.palletsprojects.com/en/3.0.x/api/#jinja2.Environment
    # - trim_blocks=True, the first newline after a block is removed (block, not variable tag!)
    # - lstrip_blocks=True, leading spaces and tabs are stripped from the start of a line to a block
    # - keep_trailing_newline=True, Preserve the trailing newline when rendering templates
    #
    # trim_blocks=True and lstrip_blocks=True -> make sure lines of {% ... %} and {# ... #} will be removed completely in render result
    #
    # For extension, plrease refer to https://jinja.palletsprojects.com/en/3.0.x/extensions/
    # - jinja2.ext.loopcontrols, add break and continue support in for loop
    #
    env = Environment(trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True, extensions=['jinja2.ext.loopcontrols'])

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

    def exists(path):
        """ Check if path exists. """
        # Only support FileSystemLoader which has a searchpath
        if not isinstance(env.loader, FileSystemLoader):
            return False
        #
        fp = os.path.join(env.loader.searchpath[0], path)
        return os.path.exists(fp)

    def getpro(key):
        """ Get property value by key, from .pyseed-properties. """
        return properties.get(key)

    env.globals['update_query'] = update_query
    env.globals['new_model'] = new_model
    env.globals['exists'] = exists
    env.globals['getpro'] = getpro
    env.add_extension(py3seed.ext.InlineGetpro)

    def split(value, separator):
        """ Split a string. """
        return value.split(separator)

    def items(value):
        """ Return items of a dict. """
        return value.items()

    def keys(value):
        """ Return keys of dict. """
        if type(value) is list:  # list of tuple
            return map(lambda x: x[0], value)
        else:
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

    def right(s: str, width: int = 4):
        """ Do indent, if content is not blank, add leading indent. """
        s = filters.do_indent(s, width)
        if s:
            s = ' ' * width + s
        #
        return s

    def last_name(path):
        """ Get last name from path, e.g, user.name -> name, user -> user. """
        return path.split('.')[-1]

    def match(values, matcher):
        """ Get the first matching field from values.
        e.g,
        - values|match('name|title|\\w+_name')
        """
        if not values:
            return None
        #
        matcher = re.compile(matcher if matcher.startswith('(') else f'({matcher})')
        if isinstance(values, dict):
            values = values.keys()
        #
        for v in values:
            if matcher.match(v):
                return v
        # If no matching, return nothing
        return None

    def fields(layout_or_schema, matcher=None, **kwargs):
        """ Get the matched fields from layout or schema. """
        if not layout_or_schema:
            return []
        #
        if isinstance(layout_or_schema, list):  # layout is [[{}, ...], ...]
            _fields = list(get_layout_fields(layout_or_schema, **kwargs))
        elif isinstance(layout_or_schema, dict):  # schema is dict {type: 'object', properties: {name, type, ... }}
            _fields = list(layout_or_schema['columns'])
        else:
            raise ValueError(f'Unsupported type to calculate fields: {type(layout_or_schema)}')
        #
        if matcher:
            # NOTE: in jinja2, you need to escape regex str, e.g, \w -> \\w
            # e.g, {{ set title_fields = layout|fields('title|name|\\w*name') }}
            matcher = re.compile(matcher if matcher.startswith('(') else f'({matcher})')
            return [f for f in _fields if matcher.match(f)]
        else:
            return _fields

    def field(layout_or_schema, matcher=None):
        """ Get the first matched field from layout or schema. """
        fields_ = fields(layout_or_schema, matcher)
        return fields_[0] if fields_ else None

    env.filters['split'] = split
    env.filters['items'] = items
    env.filters['keys'] = keys
    env.filters['quote'] = quote
    env.filters['basename'] = basename
    env.filters['urlquote'] = urlquote
    env.filters['right'] = right
    env.filters['last_name'] = last_name
    env.filters['match'] = match
    env.filters['fields'] = fields
    env.filters['field'] = field
    #
    return env


def _gen(ds: str = None):
    """ Gen. """
    include_domains = [d.strip() for d in ds.split(',')] if ds else []
    logger.info(f'Gen under domain(s) {include_domains}')
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
    domain_names, blueprint_view_names = set(), set()
    module_name = 'models'
    module_path = os.path.join('core', module_name, '__init__.py')
    if not os.path.exists(module_path):
        logger.error(f'Package does NOT exist at {module_path}')
        return False
    #
    module_spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    logger.info(f'Load models:')
    for attr in dir(module):
        attribute = getattr(module, attr)
        if inspect.isclass(attribute) and issubclass(attribute, BaseModel):
            model_name, model_class = attribute.__name__, attribute
            # Model may be imported twice, in case of typo or being used as other name
            if model_name in model_settings:
                continue
            #
            logger.info(f'{model_name}')
            # Parse model schema and views
            schema = model_class.schema()
            model_setting = {
                'schema': schema,  # dict
                **generate_names(model_name)
            }
            #
            views = []
            for k, v in model_class.__views__.items():
                # k has format domains://name, domains are sperated by |, e.g, www|miniapp://index
                if '://' not in k:
                    logger.error(f'View name {k} for model {model_name} is not valid, should be domains://name')
                    return False
                domains, name = k.split('://')
                domains = [d.strip() for d in domains.split('|')]
                # Filter views if include_domains has value
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
                if '/' in name:
                    blueprint, name = name.split('/')
                else:
                    blueprint = 'public'
                #
                layout = v.strip()
                logger.info(f'- {"|".join(domains)}://{blueprint}/{name}: {layout}')
                # Validate to make sure view name is unique
                blueprint_view_name = f'{blueprint}/{name}'
                if blueprint_view_name in blueprint_view_names:
                    logger.error(f'View {blueprint_view_name} is not unique')
                    return False
                #
                blueprint_view_names.add(blueprint_view_name)
                #
                l = parse_layout(layout, schema)
                views.append({
                    'model': model_setting,
                    'blueprint': blueprint,
                    'domains': domains,
                    'action': l['action'],
                    'params': l['params'],
                    'rows': l['rows'],
                    'layout': layout,  # NOTE: layout stores the original layout string, parsed layout is stored in rows
                    **generate_names(name)
                })
            #
            model_setting['views'] = views
            model_settings[model_name] = model_setting
    #
    if not model_settings:
        logger.error('Can not find any models to gen')
        return False
    #
    # Load properties file, which is ini format
    # https://docs.python.org/3/library/configparser.html
    #
    properties = {}
    properties_file = configparser.ConfigParser()
    properties_file.read('.pyseed-properties')
    for section in properties_file.sections():
        for k in properties_file[section]:
            properties[k] = properties_file[section][k]
    #
    # For each domain:
    # 1. Build context
    # 2. Render jinja2 templates
    #
    results = {}  # {domain: {file_gen: 0, dir_gen: 0, warnings: [], ...}}
    for domain in domain_names:
        # Domain should be a project folder, e.g, www/miniapp/android/ios
        logger.info(f'Gen for domain {domain}')
        results[domain] = {}
        #
        # Parse .pyseed-includes in current folder, files whose name ends with jinja2 and folders whose name contains syntax {{ should be included
        # e.g,
        #   www/static/js/enums.js.jinja2
        #   www/templates/{{#blueprints}}
        #   www/blueprints/__init__.py.jinja2
        #   www/blueprints/{{#blueprints}}.py.jinja2
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
            models_by_name = {}
            for v in bp['views']:  # Views
                v_name = v['name']
                logger.info(f'  {v_name}')
                #
                v_model = v['model']
                models_by_name[v_model['name']] = v_model
                # Add relation models
                for relation in v_model['schema']['relations']:
                    models_by_name[relation] = model_settings[relation]
            #
            bp['models'] = list(models_by_name.values())
        # models & blueprints can be used in all templates
        context = {
            'domain': domain,
            'models': model_settings,
            'blueprints': blueprints,
            'result': {'file_gen': 0, 'dir_gen': 0, 'warnings': []}
        }
        #
        # Do generation logic for each includes
        #
        env = _prepare_jinja2_env(properties)
        for include in includes:
            base = os.path.dirname(include)
            name = os.path.basename(include)
            _recursive_render(base, base, name, context, env)
        #
        results[domain] = context['result']
    #
    # Print results
    #
    logger.info(f'----------')
    for domain, result in results.items():
        logger.info(f'{domain}:')
        logger.info(f'  {result["dir_gen"]} dirs generated')
        logger.info(f'  {result["file_gen"]} files generated')
        logger.info(f'  {len(result["warnings"])} warnings')
        for i, warning in enumerate(result['warnings']):
            logger.info(f'    {i}. {warning}')
    logger.info(f'----------')
    logger.info(f'Generation Done!')


def _recursive_render(t_base, o_base, name, context, env):
    """ Render output folder/file, handle names having list/varible syntax.

    Supported Syntax:
      {{#blueprints}}
      {{blueprint}}
      {{#views}}
      {{view}}
      {{#models}}
      {{model}}
    """
    t_path = os.path.join(t_base, name)
    t_name = ''.join(name.split())  # Remove all the whitespace chars from name
    out_names = [t_name]  # if no matched list or varible syntax, process directly
    logger.debug(f'Process {t_path}')
    # For each value v in out_values, will put v into context using out_key
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
            out_key = 'blueprint'
            # blueprints can be access at context level
            out_values = context['blueprints']
            out_names = [t_name.replace(syntax, v['name']) for v in out_values]
        elif key == 'views':
            out_key = 'view'
            # views under current blueprint
            out_values = context['blueprint']['views']
            out_names = [t_name.replace(syntax, v['name']) for v in out_values]
        elif key == 'models':
            out_key = 'model'
            # models can be accessed at context level, NOTE: models is dict, {name: {names, schema}}}, so we use values() here
            out_values = list(context['models'].values())
            # names of blueprints/views are kebab formats because them will be used in the url directly, while modal names are always in camel case because of PEP8
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
            if key in ['blueprint', 'view']:
                out_key = key
                out_values = [context[out_key]]
                out_names = [t_name.replace(syntax, v['name']) for v in out_values]
            elif key in ['model']:
                out_key = key
                out_values = [context[out_key]]
                # Output folder/file names are in kebab format, but not camel case
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
            logger.info(f'Render {o_name}/')
            context['result']['dir_gen'] += 1
            o_path = os.path.join(o_base, o_name)
            if not os.path.exists(o_path):
                os.mkdir(o_path)
            # if output is not the same as template, need to copy includes folder
            t_includes = os.path.join(t_path, INCLUDES_FOLDER)
            o_includes = os.path.join(o_path, INCLUDES_FOLDER)
            if t_path != o_path and os.path.exists(t_includes):
                logger.debug(f'Copy {t_includes} -> {o_includes}')
                shutil.copytree(t_includes, o_includes, dirs_exist_ok=True)
            # Can use this context value for inner templates
            if out_key:
                context[out_key] = out_values[i]
            # Render recursively
            for f in sorted(os.listdir(t_path)):
                # Only process files
                if os.path.isfile(os.path.join(t_path, f)):
                    _recursive_render(t_path, o_path, f, context, env)
            # Remove out_key from context
            if out_key:
                del context[out_key]
            #
            if os.path.exists(o_includes):
                shutil.rmtree(o_includes)
    #
    # Render file
    #
    else:
        # Only process jinja2 files
        if not t_name.endswith('.jinja2'):
            return
        # Overwrite with template file content firstly
        # e.g,
        # 1. Files that has list or varible syntax, regenerate each time; The jinjas generated should be removed after generation
        #    www/templates/{{#blueprints}}/{{#views}}.html.jinja2
        #    ->
        #    www/templates/public/user-profile.html.jinja2
        #    www/templates/public/team-members.html.jinja2
        #    ...
        # 2. Files that is just a jinja, no need to overwrite just render directly; The jinja file should NOT be removed after generation
        #    www/static/js/enums.js.jinja2
        for o_name in out_names:
            o_path = os.path.join(o_base, o_name)
            # Only two cases
            # - name has list/var syntax, e.g, www/views/public/{{#views}}.html.jinja2
            # - name has not list/var syntax but parent folder has, e.g, www/templates/{{#blueprints}}/env.txt.jinja2
            if t_path != o_path:
                logger.debug(f'Copy {t_path} to {o_path}')
                shutil.copyfile(t_path, o_path)
        # Change working folder to ., so that jinja2 works ok
        abs_o_base = os.path.abspath(o_base)
        with work_in(abs_o_base):
            logger.info(f'Working at {abs_o_base}')
            # Set jinja2's path
            env.loader = FileSystemLoader('.')
            #
            for i, o_name in enumerate(out_names):
                o_file_raw = o_name.replace('.jinja2', '')
                # Python file namimg convention, e.g, pub-demo.py -> pub_demp.py
                if o_file_raw.endswith('.py'):
                    o_file_raw = o_file_raw.replace('-', '_')
                #
                # AutoMerge
                # Check if output with additional suffix exsit, if yes, go into below merging logic, otherwise, render(overwrite) directly
                #
                # - Output name with additional suffix .0:
                # A simple way to preserve custom code, always generate code to the file with suffix .0
                # e,g,
                # user-profile.html.0 exists, always generate code to user-profile.html.0, then you need to merge manually
                #
                # - Output name with additional suffix .1:
                # Using BASE, THIS and OTHER to perform a 3-way merge
                # e.g,
                # user-profile.html.1 exists, coping user-profile.html.1 to user-profile.html.BASE and user-profile.html to user-profile.html.THIS, generating user-profile.html.OTHER, then perform 3-way merge to user-profile.html
                #
                o_file_0 = o_file_raw + '.0'
                o_file_1 = o_file_raw + '.1'
                o_file_base = o_file_raw + '.BASE'
                o_file_this = o_file_raw + '.THIS'
                o_file_other = o_file_raw + '.OTHER'
                if os.path.exists(o_file_0):
                    o_file = o_file_0
                elif os.path.exists(o_file_1):
                    # After manually merge, need to remove BASE/THIS/OTHER files mannually
                    if os.path.exists(o_file_other):
                        msg = f'Please solve last merging conflicts of {o_file_raw}'
                        context['result']['warnings'] += [msg]
                        logger.warning(msg)
                        continue
                    # BASE, copy from .1
                    shutil.copyfile(o_file_1, o_file_base)
                    # THIS, copy from exsiting file
                    shutil.copyfile(o_file_raw, o_file_this)
                    # OTHER, newly genearted file
                    o_file = o_file_other
                else:
                    o_file = o_file_raw
                #
                logger.info(f'Render {o_file}')
                context['result']['file_gen'] += 1
                # Push current key to context
                if out_key:
                    context[out_key] = out_values[i]
                #
                # Render file
                #
                try:
                    tmpl = env.get_template(o_name)
                except TemplateSyntaxError as exception:
                    exception.translated = False
                    raise
                #
                rendered = tmpl.render(**context)
                with open(o_file, 'w', encoding='utf-8') as f:
                    f.write(rendered)
                #
                # Perform 3-way merge
                #
                if os.path.exists(o_file_1):
                    logger.info(f'Perform 3-way merge of {o_file_raw}')
                    # BASE
                    with open(o_file_base, 'r', encoding='utf-8') as f:
                        base = f.read().splitlines(True)
                    # THIS
                    with open(o_file_this, 'r', encoding='utf-8') as f:
                        this = f.read().splitlines(True)
                    # OTHER
                    with open(o_file_other, 'r', encoding='utf-8') as f:
                        other = f.read().splitlines(True)
                    #
                    m3 = Merge3(base, other, this)
                    merged = ''.join(m3.merge_lines('OTHER', 'THIS'))
                    # print('\n'.join(m3.merge_annotated()))
                    with open(o_file_raw, 'w', encoding='utf-8') as f:
                        f.write(merged)
                    # copy OTHER to .1, so that next time we can use it as BASE
                    shutil.copyfile(o_file_other, o_file_1)
                    # Has conficts, need to solve manually
                    if '=======' in merged:
                        msg = f'Please solve merging conflicts of {o_file_raw}'
                        context['result']['warnings'] += [msg]
                        logger.warning(msg)
                    else:
                        # Remove BASE/THIS/OTHER files
                        os.remove(o_file_base)
                        os.remove(o_file_this)
                        os.remove(o_file_other)
                # Remove out_key from context
                if out_key:
                    del context[out_key]
                # Remove template file
                if t_path != os.path.join(o_base, o_name):
                    os.remove(o_name)


def main(args: List[str]) -> bool:
    """ Main. """
    parser = argparse.ArgumentParser(prog="pyseed gen")
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
    return _gen(parsed_args.d)
