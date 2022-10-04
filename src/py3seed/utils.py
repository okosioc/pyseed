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
import math
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
    if name in ('', '-', '$') or re.match(r'[\d+]+', name):
        return {
            'name': name,
        }
    else:
        name_hyphen = re.sub(r'[.,?=#+]', '-', ''.join(name.split()))  # e.g, plan.members-form -> plan-members-form
        name_snake = inflection.underscore(name_hyphen)
        name_kebab = inflection.dasherize(name_snake)
        name_title = inflection.titleize(name_hyphen)
        return {
            'name': name,  # => SampleModel
            'name_lower': name.lower(),  # => samplemodel
            'name_snake': name_snake,  # => sample_model
            'name_snake_plural': inflection.pluralize(name_snake),  # => sample_models
            'name_kebab': name_kebab,  # => sample-model
            'name_kebab_plural': inflection.pluralize(name_kebab),  # => sample-models
            'name_title': name_title,  # => Sample Model
            'name_title_lower': name_title.lower(),  # => sample model
            'name_title_lower_plural': inflection.pluralize(name_title.lower()),  # => sample models
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
        """ Parse column string.

        Column string possible values:
        1) blank column prints only a placeholder
        2) row only contains one hyphen(-) prints <hr>
        3) summary column($) prints model's summary
        4) number column prints a group of fields, e.g, __groups__=['', ''], using 0 as column name should print groups[0]
        5) single column with param and span, e.g, column?is_param=true#6
        6) contains inner columns, e,g, (column?is_param=true, column)?is_param=true#6
        """
        column_str = column_str.strip()
        ret = {}
        # Parse span at the end, i.e, a#4,(b,c)#8
        span_match = span_regex.match(column_str)
        if span_match:
            column_str = span_match.group(1)
            ret.update({'span': int(span_match.group(2))})
        # Check bracket
        bracket_match = bracke_regex.match(column_str)
        # Inner column, e.g, a,(b,c)
        if bracket_match:
            column_str = bracket_match.group(1)
            query_str = bracket_match.group(2)
            children = [_parse_column(cs) for cs in comma_regex.split(column_str)]
            ret.update({'children': children})
            # Join children's name
            # e.g, a,(b?p=1,c#6) -> b+c
            column_str = '+'.join(map(lambda x: x['name'], children))
        # Single level column, e.g, a,b,c
        else:
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
                # Find model by name, ignoring cases and underlines
                found = next(
                    (m for n, m in models.items() if n.lower() in [model_name.lower(), inflection.camelize(model_name).lower()]), None
                )
                if found:
                    action = tokens[1]
                    ret.update({'model': found, 'sub': sub, 'action': action})
                    # Append to return seeds
                    seeds.append(ret)
        # Names
        ret.update(generate_names(column_str))
        # Params
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


def iterate_layout(layout, groups=[]):
    """ Each column in layout can be blank('')/hyphen(-)/summary($)/group(number)/field(string)/inner fields(has children), iterate the whole layout and return field names only.

    :param layout: Parsed layout
    :param groups: Group index in layout need to refer to this list
    :return:
    """
    for row in layout:
        for col in row:
            col_name = col['name']
            if col.get('children'):
                yield from iterate_layout([col['children']], groups)
            elif col_name.isdigit():
                yield from iterate_layout(groups[int(col_name)], groups)
            elif col_name in ('', '-', '$'):
                pass
            else:
                yield col_name


class Pagination(object):
    """ Pagination support. """

    def __init__(self, page, per_page, total_count):
        self.page = page
        self.per_page = per_page
        self.total_count = total_count

    @property
    def pages(self):
        return int(math.ceil(self.total_count / float(self.per_page)))

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def prev(self):
        return self.page - 1 if self.has_prev else None

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def next(self):
        return self.page + 1 if self.has_next else None

    @property
    def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
                    (num > self.page - left_current - 1 and num < self.page + right_current) or \
                    num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num

    def __iter__(self):
        """ Can use dict(pagination) for jsonify. """
        for key in ['page', 'pages', 'prev', 'next']:
            yield key, getattr(self, key)
        #
        yield 'iter_pages', list(self.iter_pages)
