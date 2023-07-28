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

from flask import request
from jinja2 import Environment, TemplateSyntaxError, FileSystemLoader, filters
from werkzeug.urls import url_quote, url_encode

from py3seed import registered_models, BaseModel, TemplateError, LayoutError
from py3seed.utils import work_in, generate_names, get_layout_fields, parse_layout
from py3seed.merge3 import Merge3

logger = logging.getLogger('pyseed')
INCLUDES_FOLDER = '__includes'


def _prepare_jinja2_env():
    """ Prepare env for rendering jinja2 templates. """
    #
    # For more env setting, please refer to https://jinja.palletsprojects.com/en/3.0.x/api/#jinja2.Environment
    # - trim_blocks=True, the first newline after a block is removed (block, not variable tag!)
    # - lstrip_blocks=True, leading spaces and tabs are stripped from the start of a line to a block
    # - keep_trailing_newline=True, Preserve the trailing newline when rendering templates
    #
    # trim_blocks=True and lstrip_blocks=True -> make sure lines of {% ... %} and {# ... #} will be removed completely in render result
    # keep_trailing_newline=True -> keep trailing newline to so that you can use indent filter to include the macro with a tailing newline
    #
    # For extension, plrease refer to https://jinja.palletsprojects.com/en/3.0.x/extensions/#loopcontrols-extension
    #
    env = Environment(trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True, extensions=['jinja2.ext.loopcontrols'])

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

    def right(s: str, width: int = 4):
        """ Do indent, if content is not blank, add leading indent. """
        s = filters.do_indent(s, width)
        if s:
            s = " " * width + s
        #
        return s

    env.filters['split'] = split
    env.filters['items'] = items
    env.filters['keys'] = keys
    env.filters['quote'] = quote
    env.filters['basename'] = basename
    env.filters['urlquote'] = urlquote
    env.filters['right'] = right

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

    def parse_layout_fields(layout):
        """ Get layout fields.

        each column in layout can be blank('')/hyphen(-)/group(integer&float)/field(string) suffixed with query and format-span string
        this function will return a list of field names.
        """
        return list(get_layout_fields(layout))

    def exists(path):
        """ Check if path exists. """
        # Only support FileSystemLoader which has a searchpath
        if not isinstance(env.loader, FileSystemLoader):
            return False
        #
        fp = os.path.join(env.loader.searchpath[0], path)
        return os.path.exists(fp)

    env.globals['update_query'] = update_query
    env.globals['new_model'] = new_model
    env.globals['match_field'] = match_field
    env.globals['parse_layout_fields'] = parse_layout_fields
    env.globals['exists'] = exists
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
    domain_names, view_names = set(), set()
    module_name = 'models'
    module_path = os.path.join('core', module_name, '__init__.py')
    if not os.path.exists(module_path):
        logger.error(f'Package does NOT exist at {module_path}')
        return False
    module_spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    logger.info(f'Load models:')
    for attr in dir(module):
        attribute = getattr(module, attr)
        if inspect.isclass(attribute) and issubclass(attribute, BaseModel):
            model_name, model_class = attribute.__name__, attribute
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
                #
                layout = v['layout'].strip()
                logger.info(f'- {blueprint}/{name}: {layout}')
                # Validate to make sure view name is unique
                if name in view_names:
                    logger.error(f'View name {v["name"]} is not unique')
                    return False
                #
                view_names.add(name)
                #
                l = parse_layout(layout, schema)
                views.append({
                    'model': model_setting,
                    'blueprint': blueprint,
                    'domains': domains,
                    'action': l['action'],
                    'params': l['params'],
                    'rows': l['rows'],
                    'layout': layout,
                    **generate_names(name)
                })
            # Views may be empty if no views match
            if not views:
                continue
            #
            model_setting['views'] = views
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
                v_name = v['name']
                logger.info(f'  {v_name}')
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
      {{#models}}
      {{model}}
    """
    t_path = os.path.join(t_base, name)
    t_name = ''.join(name.split())  # Remove all the whitespace chars from name
    out_names = [t_name]  # if no matched list or varible syntax, process directly
    logger.debug(f'Render {t_path} -> {out_names}')
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
        elif key == 'models':
            out_key = '__model'
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
            # if output is not the same as template, need to copy includes folder
            t_includes = os.path.join(t_path, INCLUDES_FOLDER)
            o_includes = os.path.join(o_path, INCLUDES_FOLDER)
            if t_path != o_path  and os.path.exists(t_includes):
                logger.debug(f'Copy {t_includes} -> {o_includes}')
                shutil.copytree(t_includes, o_includes)
            # Can use this context value in sub folders and files
            if out_values:
                context[out_key] = out_values[i]
            # Render recursively
            for f in sorted(os.listdir(t_path)):
                # Only process files
                if os.path.isfile(os.path.join(t_path, f)):
                    _recursive_render(t_path, o_path, f, context, env)
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
            o_context = {k: v for k, v in context.items() if not k.startswith('__')}
            #
            for i, o_name in enumerate(out_names):
                o_file_raw = o_name.replace('.jinja2', '')
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
                # Using .1(BASE), .11(THIS) and .111(OTHER) to perform a 3-way merge
                # e.g,
                # user-profile.html.1 exists, coping user-profile.html as user-profile.html.11, generating user-profile.html.111, then perform 3-way merge to user-profile.html
                #
                o_file_0 = o_name.replace('.jinja2', '.0')
                o_file_1 = o_name.replace('.jinja2', '.1')
                o_file_11 = o_name.replace('.jinja2', '.11')
                o_file_111 = o_name.replace('.jinja2', '.111')
                if os.path.exists(o_file_0):
                    o_file = o_file_0
                elif os.path.exists(o_file_1):
                    if os.path.exists(o_file_111):
                        logger.warning(f'Please solve last merging conflicts of {o_file_raw}')
                        continue
                    # THIS, copy from exsiting file
                    shutil.copyfile(o_file_raw, o_file_11)
                    shutil.copymode(o_file_raw, o_file_11)
                    # OTHER, newly genearted file
                    o_file = o_file_111
                else:
                    o_file = o_file_raw
                #
                logger.info(f'Render {o_file}')
                # Remove __ so that object can be accessed in template
                if out_key:
                    o_context[out_key[2:]] = out_values[i]
                #
                # Render file
                #
                try:
                    tmpl = env.get_template(o_name)
                except TemplateSyntaxError as exception:
                    exception.translated = False
                    raise
                #
                rendered = tmpl.render(**o_context)
                with open(o_file, 'w', encoding='utf-8') as f:
                    f.write(rendered)
                #
                # Perform 3-way merge
                #
                if os.path.exists(o_file_1):
                    logger.info(f'Perform 3-way merge of {o_file_raw}')
                    # BASE
                    with open(o_file_1, 'r', encoding='utf-8') as f:
                        base = f.read().splitlines(True)
                    # THIS
                    with open(o_file_11, 'r', encoding='utf-8') as f:
                        this = f.read().splitlines(True)
                    # OTHER
                    with open(o_file_111, 'r', encoding='utf-8') as f:
                        other = f.read().splitlines(True)
                    #
                    m3 = Merge3(base, other, this)
                    merged = ''.join(m3.merge_lines('OTHER', 'THIS'))
                    # print('\n'.join(m3.merge_annotated()))
                    with open(o_file_raw, 'w', encoding='utf-8') as f:
                        f.write(merged)
                    # Has conficts, need to solve manually
                    if '=======' in merged:
                        logger.warning(f'Please solve merging conflicts of {o_file_raw}')
                    else:
                        # Rename .111 to .1 for next merging
                        os.rename(o_file_111, o_file_1)
                        # Remove .11
                        os.remove(o_file_11)
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
