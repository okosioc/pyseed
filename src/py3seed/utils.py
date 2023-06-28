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
import logging

from .error import LayoutError
import inflection

logger = logging.getLogger('pyseed')


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


# Match span
SPAN_REGEX = re.compile(r'^(.*)#([0-9]+)$')


def parse_layout(body, schema):
    """ Parse layout defined in a model action.
    e.g,
    'demo/user-profile': {              # action name
        'domains': ['www'],             # domains that this action is available
        'layout': '''#!form?param=1     # first line is action line defining action type and params, i.e, query, read, read_by_key, form
            $#4,           0#8
              avatar         name
              name           phone
              status         intro
              roles          avatar
              email
              phone
              create_time
        ''',
    }
    Return {action, params, rows}
    e.g,
    {
        action: form
        params: {
            param: 1,
        },
        rows: [                         # each column is a dict, which has name/params/span and inner rows
            {name: $, rows:[...]},
            {name: 0, rows:[...]},
        ]
    }
    """

    def _parse_lines(level, _lines, _schema):
        """ Recursively parse lines. """
        # logger.debug('Parse lines:\n' + '\n'.join(_lines))
        _rows = []
        # Get the indexes of lines that has same indent with first line
        first_line = _lines[0]
        first_indent = len(first_line) - len(first_line.lstrip())
        indexes = []
        for index in range(len(_lines)):
            line = _lines[index]
            indent = len(line) - len(line.lstrip())
            if indent == first_indent:
                indexes.append(index)
            elif indent < first_indent:
                raise LayoutError(f'Invalid indent {indent} < {first_indent}: ' + line.replace(" ", "."))
            else:
                diff = first_indent - indent
                if diff % 2 != 0:
                    raise LayoutError(f'Invalid indent {indent} - {first_indent} is odd: ' + line.replace(" ", "."))
        # Parse each segment
        for i in range(0, len(indexes)):
            index = indexes[i]
            segment = _lines[index: indexes[i + 1]] if i < len(indexes) - 1 else _lines[index:]
            # Remove the indent of each line
            segment = [l[first_indent:] for l in segment]
            # Parse segment, first line is fields seperated by comma and the rest are layout of each field
            index_line = segment[0]
            columns = [_parse_column(c) for c in index_line.split(',')]
            # Validate inddex line, while inner layout will be validated recursively
            for column in columns:
                col_name = column['name']
                # Blank column
                if not col_name:
                    pass
                # Hyphen column
                elif col_name == '-':
                    pass
                # Summary column
                elif col_name == '$':
                    pass
                # Group column
                elif col_name.isdigit():
                    pass
                else:
                    keys = _schema['properties'].keys()  # type of _schema is always a object
                    if col_name not in keys:
                        raise LayoutError(f'Field {col_name} not found in schema')
            # Has inner layout
            if len(segment) > 1:
                logger.debug(f'Parsing level {level} segment:\n' + '\n'.join(segment))
                body_lines = segment[1:]
                # Inject layout for each column
                for j in range(0, len(columns)):
                    column = columns[j]
                    col_name = column['name']
                    start_position = index_line.index(column['raw'])
                    if j < len(columns) - 1:
                        end_position = index_line.index(columns[j + 1]['name'])
                        col_lines = [l[start_position:end_position] for l in body_lines]
                    else:
                        col_lines = [l[start_position:] for l in body_lines]
                    # Remove empty lines
                    col_lines = [l for l in col_lines if l.strip()]
                    if not col_lines:  # some column may have not inner layout, e.g, blank column/simple field
                        continue
                    #
                    logger.debug(f'Column {i}, {j}: {col_name}\n' + '\n'.join(col_lines))
                    #
                    # Column name possible values:
                    # 1) blank column prints only a placeholder
                    # 2) hyphen(-) prints line separator, i.e, <hr/>
                    # 3) group column(digit) combines multiple columns
                    # 4) summary column($) prints model's summary
                    #
                    # While schema is a subset of Object Schema from OAS 3.0,
                    # In order to keep all the things simple, we do not use complex keywords such as oneOf, patternProperties, additionalProperties, etc.
                    # - https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#schemaObject
                    # - https://swagger.io/docs/specification/data-models/
                    # e.g,
                    # _schema = {
                    #     type: object,
                    #     properties: {
                    #         name: {type: string},
                    #         avatar: {type: string, format: image},
                    #         status: {type: string, enum: [normal, rejected]},
                    #         team: {
                    #             type: object,
                    #             properties: {
                    #                 name: {type: string},
                    #                 ...
                    #             }
                    #         },
                    #         logins: {
                    #             type: array,
                    #             items: {
                    #                 type: object,
                    #                 properties: {
                    #                     ip: {type: string},
                    #                     time: {type: string, format: date-time}
                    #                 }
                    #             }
                    #         },
                    #     }
                    # }
                    # Blank column
                    if not col_name:
                        pass
                    # Hyphen column
                    elif col_name == '-':
                        pass
                    # Summary column
                    elif col_name == '$':
                        column['rows'] = _parse_lines(level + 1, col_lines, _schema)
                    # Group column
                    elif col_name.isdigit():
                        column['rows'] = _parse_lines(level + 1, col_lines, _schema)
                    else:
                        inner_schema = _schema['properties'][col_name]
                        inner_type = inner_schema['type']
                        if inner_type in ['object', 'array']:
                            if not col_lines:
                                raise LayoutError(f'Field {col_name} should have layout')
                            # Schema passing recursively should always be object
                            column['rows'] = _parse_lines(level + 1, col_lines, inner_schema if inner_type == 'object' else inner_schema['items'])
                        else:
                            raise LayoutError(f'{inner_type.capitalize()} field {col_name} can not have inner layout')
            #
            _rows.append(columns)
        #
        return _rows

    def _parse_column(column_str):
        """ Parse column string, having params and span, e.g, a?param=1#4. """
        column_str = column_str.strip()
        ret = {
            'raw': column_str,
        }
        # Parse span at the end, e.g, a?param=1#4
        span_match = SPAN_REGEX.match(column_str)
        if span_match:
            column_str = span_match.group(1)
            ret.update({'span': int(span_match.group(2))})
        # Parse params, e.g, a?param=1#4
        if '?' in column_str:
            column_str, params = _parse_query_str(column_str)
            ret.update({'params': params})
        #
        ret.update({'name': column_str})
        #
        return ret

    def _parse_query_str(_query_str):
        """ Parse query string. """
        _path, _query_str = _query_str.split('?')
        _params = {}
        for p in _query_str.split('&'):
            _key, _value = p.split('=')
            #
            _key = _key.lower()
            _value = _value.strip()
            if _key.startswith('has_') or _key.startswith('is_'):
                if _value.lower() in ['1', 'true', 'yes']:
                    _value = True
                else:
                    _value = False
            elif _value.startswith('[') or _value.startswith('{'):
                try:
                    _value = json.loads(_value)  # Need to use double quotes for string values or key names
                except ValueError as e:
                    pass
            #
            _params[_key] = _value
        #
        return _path, _params

    # Return {action, params, rows}
    # Default action is read
    action = 'read'
    params = {}
    # Remove empty lines and remove trailing spaces for each line
    lines = body.splitlines()
    lines = [l.rstrip() for l in lines if l.strip()]
    if not lines:
        logger.error('Layout can NOT be empty')
        return None
    # Parse action line
    action_line = lines[0]
    # If it is action line, parse action and params
    if action_line.startswith('#!'):
        action_str = action_line[2:].strip()
        lines = lines[1:]
        # Parse params, e.g, form?param=1
        if '?' in action_str:
            action, params = _parse_query_str(action_str)
    #
    rows = _parse_lines(0, lines, schema)
    #
    return {
        'action': action,
        'params': params,
        'rows': rows
    }


def parse_layout1(body, models=None):
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
    # Rows are [column], column should be {name:str, params:{}, span:int, children:[column], model:{name:str, schema:{}}}, name and params are required
    rows, seeds = [], []

    # Match span
    span_regex = re.compile(r'^(.*)#([0-9]+)$')
    # Match bracket
    bracke_regex = re.compile(r'^\((.*)\)(.*)')
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
                # Only generate for seeds w/o alphanumeric suffix
                #   Block-read, generate
                #   Block-read-feature-1, skip
                #   Block-read-feature-2, skip
                #   Quote-query, generate
                #   Quote-query-1, generate
                tokens = column_str.split('-')
                model_name = tokens[0]
                sub = None
                # Sub model and only support one level sub model
                if '.' in model_name:
                    model_name, sub = model_name.split('.')
                # Find model by name, ignoring cases and underlines
                # e.g, DemoProject-read, demo_project_read can match model DemoProject
                found = next(
                    (m for n, m in models.items() if n.lower() in [model_name.lower(), inflection.camelize(model_name).lower()]), None
                )
                if found:
                    action = tokens[1]
                    suffix = '-'.join(tokens[2:])
                    # NOTE: The numeric suffix will be ignored so that the seed will be generated, we using it to generate seeds with different params
                    # e.g,
                    #   Quote-query?is_card=true
                    #   Quote-query-1?is_card=true&has_search=false
                    if suffix.isdigit():
                        suffix = ''
                    #
                    ret.update({'model': found, 'sub': sub, 'action': action, 'suffix': suffix})
                    # Append to return seeds
                    seeds.append(ret)
        # Names, if models is specified, means it is parsing layout for view, need to generate names for each seed
        if models:
            ret.update(generate_names(column_str))
        else:
            ret.update({'name': column_str})
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
