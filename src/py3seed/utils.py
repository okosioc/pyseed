# -*- coding: utf-8 -*-
"""
    utils
    ~~~~~~~~~~~~~~

    Util functions.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/9/8
"""

import contextlib
import json
import os
import re
import shutil
import stat

import inflection


def force_delete(func, path, exc_info):
    """ Error handler for `shutil.rmtree()` equivalent to `rm -rf`.

    Usage: `shutil.rmtree(path, onerror=force_delete)`
    From https://docs.python.org/3/library/shutil.html#rmtree-example
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(path):
    """ Remove a directory and all its contents. Like rm -rf on Unix.

    :param path: A directory path.
    """
    shutil.rmtree(path, onerror=force_delete)


@contextlib.contextmanager
def work_in(dirname=None):
    """ Context manager version of os.chdir.

    When exited, returns to the working directory prior to entering.
    """
    curdir = os.getcwd()
    try:
        if dirname is not None:
            os.chdir(dirname)
        yield
    finally:
        os.chdir(curdir)


def generate_names(name):
    """ Generate names, which can be used directly in code generation. """
    if name:
        name_hyphen = re.sub(r'[.,?=#+]', '-', ''.join(name.split()))  # e.g, plan.members-form -> plan-members-form
        return {
            'name': name,  # => SampleModel
            'name_lower': name.lower(),  # => samplemodel
            'name_kebab': inflection.dasherize(inflection.underscore(name_hyphen)),  # => sample-model
            'name_camel': inflection.camelize(name_hyphen, uppercase_first_letter=False),  # => sampleModel
            'name_snake': inflection.underscore(name_hyphen),  # => sample_model
            'name_snake_plural': inflection.tableize(name_hyphen),  # => sample_models
            'name_title': inflection.titleize(name_hyphen),  # => Sample Model
        }
    else:
        return {
            'name': '',
        }


def parse_layout(body, models={}):
    """ Parse layout defined in model.__layout__ or seed file's view layout

    body is a multiline string:
    e.g,
    1) layout in a model
    __layout__ = '''
    $, (info, password)
    logs
    '''
    2) layout of a view in seed file
    layout: |=
      user-summary, user.timeline-read
    """
    # Returns
    # Rows are [column], while column should be {name:str, params:{}, span:int, children:[column], model:{name:str, schema:{}}}
    rows, seeds = [], []

    # Match span
    span_regex = re.compile(r'^(.*)#([0-9]+)$')
    # Match bracket
    bracke_regex = re.compile(r'^[\(](.*)[\)](.*)')
    # Use a negative lookahead to match all the commas which are not inside the parenthesis
    comma_regex = re.compile(r',\s*(?![^()]*\))')

    def _parse_column(column_str):
        """ Parse column string. """
        column_str = column_str.strip()
        ret = {}
        # Parse span at the end, i.e, a#4,(b,c)#8
        span_match = span_regex.match(column_str)
        if span_match:
            column_str = span_match.group(1)
            ret.update({'span': int(span_match.group(2))})
        # Check bracket
        bracket_match = bracke_regex.match(column_str)
        if bracket_match:  # Inner column, e.g, a,(b,c)
            column_str = bracket_match.group(1)
            query_str = bracket_match.group(2)
            children = [_parse_column(cs) for cs in comma_regex.split(column_str)]
            ret.update({'children': children})
            # Join children's name
            # e.g, a,(b?p=1,c#6) -> b+c
            column_str = '+'.join(map(lambda x: x['name'], children))
        else:  # Single level column, e.g, a,b,c
            if '?' in column_str:
                column_str, query_str = column_str.split('?')
            else:
                query_str = None
            # If is seed file's view layout, parse model and action
            if models:
                # model-action-suffix
                # Suffix is used to distinguish seeds with different params, e.g:
                #   user-form-0?is_horizontal=true
                #   user-form-1?is_horizontal=false
                tokens = column_str.split('-')
                model_name = tokens[0]
                sub = None
                # Sub model and only support one level sub model
                if '.' in model_name:
                    model_name, sub = model_name.split('.')
                # Find model by name
                found = next((m for n, m in models.items() if n.lower() == model_name.lower()), None)
                if found:
                    action = tokens[1]
                    ret.update({'model': found, 'sub': sub, 'action': action})
                    # Append to return seeds
                    seeds.append(ret)
        #
        ret.update(generate_names(column_str))
        #
        params = {}
        if query_str:
            # Parse params, i.e, a?is_card=true,(b,c)?is_tab=true
            for p in query_str.split('&'):
                key, value = p.split('=')
                params[key] = _parse_varible_value(key, value)
        #
        ret.update({'params': params})
        #
        return ret

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
                value = json.loads(value)  # Need to use double quotes for string values or key names
            except ValueError as e:
                pass
        #
        return value

    #
    lines = body.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line:  # Skip blank lines
            continue
        #
        row = [_parse_column(c) for c in comma_regex.split(line)]
        rows.append(row)
    #
    return rows, seeds
