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

from py3seed import inflection, LayoutError, Format

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
            'name_snake': name_snake,  # => sample_model, e.g, python package&module name
            'name_snake_plural': inflection.pluralize(name_snake),  # => sample_models
            'name_kebab': name_kebab,  # => sample-model, e.g, html folder&file name
            'name_kebab_plural': inflection.pluralize(name_kebab),  # => sample-models
            'name_title': name_title,  # => Sample Model
            'name_title_lower': name_title.lower(),  # => sample model
            'name_title_lower_plural': inflection.pluralize(name_title.lower()),  # => sample models
        }


# Match span
FORMAT_SPAN_REGEX = re.compile(r'^(.*)#([a-zA-Z_-]*)([0-9]*)$')


def parse_layout(body, schema):
    """ Parse layout defined in a model view.

    Layout is multi-line string defined in a model view.
    e.g,
    'www|miniapp://demo/user-profile': {    # domains can be separated by |, blueprint is demo and view is user-profile
        'layout': '''#!form?param=1         # first line is action line defining action type and params, i.e, query, read, read_by_key, form
            1#4,           2#8
              avatar         name
              name           phone
              status         intro
              roles          avatar
              email
              phone
              create_time
        ''',
    }

    Schema is a subset of Object Schema from OAS 3.0,
    In order to keep all the things simple, we do not use complex keywords such as oneOf, patternProperties, additionalProperties, etc.
    - https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#schemaObject
    - https://swagger.io/docs/specification/data-models/
    e.g,
    _schema = {
        type: object,
        properties: {
            name: {type: string},
            avatar: {type: string, format: image},
            status: {type: string, enum: [normal, rejected]},
            team: {
                type: object,
                properties: {
                    name: {type: string},
                    ...
                }
            },
            logins: {
                type: array,
                items: {
                    type: object,
                    properties: {
                        ip: {type: string},
                        time: {type: string, format: date-time}
                    }
                }
            },
        }
    }

    Return {action, params, rows}.
    e.g,
    {
        action: form
        params: {
            param: 1,
        },
        rows: [[                         # each column is a dict, which has name/params/format/span and inner rows
            {name: $, rows:[...]},
            {name: 0, rows:[...]},
        ]]
    }
    """

    # Sometimes we may encounter circular reference, so we need to use a global variable to store object schemas
    object_schemas = {}

    def _parse_lines(level, _lines, _schema, _action):
        """ Recursively parse lines. """
        # Schema should be always a object schema
        object_schemas[_schema['py_type']] = _schema
        leading = '- ' * (level + 1)  # 2 spaces for each level
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
        # Parse each segment
        for i in range(0, len(indexes)):
            index = indexes[i]
            segment = _lines[index: indexes[i + 1]] if i < len(indexes) - 1 else _lines[index:]
            # Remove the indent of each line
            segment = [l[first_indent:] for l in segment]
            # Parse segment, first line is fields seperated by comma and the rest are layout of each field
            index_line = segment[0]
            columns = [_parse_column(c) for c in index_line.split(',')]
            #
            # Cut inner layout
            #
            if len(segment) > 1:
                # logger.debug(f'{leading}Parsing level {level} segment:\n' + '\n'.join(segment))
                body_lines = segment[1:]
                # Inject layout for each column
                for j in range(0, len(columns)):
                    column = columns[j]
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
                    column['lines'] = col_lines
            #
            # Parse inner layout and do validation
            #
            for j in range(0, len(columns)):
                column = columns[j]
                col_name = column['name']
                #
                col_lines = column.get('lines', [])
                logger.debug(f'{leading}Column ({i},{j}): {col_name}' + (('\n' + '\n'.join(col_lines)) if col_lines else ''))
                # Validate each line's indent
                for l in col_lines:
                    indent = len(l) - len(l.lstrip())
                    if indent % 2 != 0:
                        raise LayoutError(f'Invalid indent {indent}: ' + l.replace(" ", "."))
                #
                # Column name possible values:
                # 1) blank column prints only a placeholder
                # 2) hyphen(-) prints line separator, i.e, <hr/>
                # 3) group column(integer/float) combines multiple fields
                #
                # Blank column
                if not col_name:
                    pass
                # Hyphen column
                elif col_name == '-':
                    pass
                # Group column, only contains number and dot(.)
                elif col_name.replace('.', '').isdigit():
                    if not col_lines:
                        raise LayoutError(f'Group {col_name} should have inner layout')
                    #
                    column['rows'] = _parse_lines(level + 1, col_lines, _schema, _action)
                else:
                    # May need other validations:
                    # - update a back relation field
                    # - update a non-editable field
                    # However, we do NOT do above validation here, as it depends on formats also
                    # Some formats are used for display only, i.e, summary, so we do not need to validate the fields under a summary group
                    if col_name not in _schema['properties']:  # type of _schema is always a object
                        raise LayoutError(f'Field {col_name} not found in schema')
                    #
                    column_schema = _schema['properties'][col_name]
                    column_type = column_schema['type']
                    inner_schema = None
                    if column_type == 'object':
                        inner_schema = column_schema
                        # Self-reference schema, inner schema should be processed before so that it can be found in object_schemas
                        # Just replace the properties as we may define differnt icon/title/description for current object
                        if 'ref' in column_schema:
                            inner_schema['properties'] = object_schemas[column_schema['ref']]['properties']
                    elif column_type == 'array':
                        # Self-reference schema, inner schema should be processed before so that it can be found in object_schemas
                        if 'ref' in column_schema['items']:
                            inner_schema = object_schemas[column_schema['items']['ref']]
                        else:
                            inner_schema = column_schema['items'] if column_schema['items']['type'] == 'object' else None
                    #
                    if inner_schema:
                        # Inner layout is optional for inner object
                        if col_lines:
                            column['rows'] = _parse_lines(level + 1, col_lines, inner_schema, _action)  # Schema passing recursively should always be an object
                    else:
                        if col_lines:
                            raise LayoutError(f'{column_type.capitalize()} field {col_name} can not have inner layout')
                    #
                    column.pop('lines', None)
            #
            _rows.append(columns)
        #
        return _rows

    def _parse_column(column_str):
        """ Parse column string, having params and format-span, e.g, a?param=1#4. """
        column_str = column_str.strip()
        ret = {
            'raw': column_str,
            'format': None,
            'span': None,
            'params': {},
        }
        # Parse span at the end, e.g, a?param=1#summary4
        format_span_match = FORMAT_SPAN_REGEX.match(column_str)
        if format_span_match:
            column_str = format_span_match.group(1)
            if format_span_match.group(2):
                ret.update({'format': format_span_match.group(2)})  # -> summary
            #
            if format_span_match.group(3):
                ret.update({'span': int(format_span_match.group(3))})  # -> 4
        # Parse params, e.g, a?param=1#4
        if '?' in column_str:
            column_str, column_params = _parse_query_str(column_str)
            ret.update({'params': column_params})
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
    rows = _parse_lines(0, lines, schema, action)
    #
    return {
        'action': action,
        'params': params,
        'rows': rows
    }


def get_layout_fields(layout, exclude_formats=(Format.SUMMARY,)):
    """ Do not recursively parse inner object/array, only return current level field names. """
    if not layout:
        return []
    #
    for row in layout:
        for col in row:
            col_name = col['name']
            # NOTE: Ignore the groups with summary format, because they are used for reference only
            # e.g,
            # - 1#summary4 is used to display a summary card of current object
            # - project#summary4 is used to display a summary card of a related object or inner object
            if col['format'] in exclude_formats:
                continue
            # Blank column
            if not col_name:
                pass
            # Hyphen column
            elif col_name == '-':
                pass
            # Group column
            elif col_name.replace('.', '').isdigit():
                yield from get_layout_fields(col['rows'])
            else:
                # Return current level field names, do not recursively parse inner object/array
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
