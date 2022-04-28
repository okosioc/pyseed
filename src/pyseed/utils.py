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


def parse_layout(body, models=[]):
    """ Parse layout defined in model.__layout__ or seed file's view layout

    body is a multiline string:
    e.g,
    1) layout in a model
    __layout__ = '''
    $, info/password
    logs
    '''
    2) layout of a view in seed file
    layout: |=
      user-summary, user.timeline-read
    """

    def _parse_column(column_str):
        """ Parse column string. """
        # Parse params
        params = {}
        if '?' in column_str:
            column_str, query = column_str.split('?')
            for p in query.split('&'):
                key, value = p.split('=')
                params[key] = _parse_varible_value(key, value)
        #
        ret = {'params': params, **generate_names(column_str)}
        # If is seed file's view layout, parse model and action
        if models:
            # model-action-suffix
            # Suffix is used to distinguish seeds with different params, e.g,
            #   user-form-0?is_horizontal=true
            #   user-form-1?is_horizontal=false
            tokens = column_str.split('-')
            name = tokens[0]
            sub = None
            # Sub model and only support one level sub model
            if '.' in name:
                name, sub = name.split('.')
            # Find model by name
            found = next((m for n, m in models.items() if n.lower() == name.lower()), None)
            if found:
                action = tokens[1]
                ret.update({'model': found, 'sub': sub, 'action': action})
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

    # rows are [{} or [{}]], seeds are columns with a model
    rows, seeds = [], []
    lines = body.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line:  # Skip blank lines
            continue
        #
        row = []
        for c in line.split(','):
            if '/' in c:  # Inner column, e.g, a,b/c
                column = []
                for cc in c.split('/'):
                    cc = cc.strip()
                    col = _parse_column(cc)
                    column.append(col)
                    if 'model' in col:
                        seeds.append(col)
            else:  # Single level column, e.g, a,b,c
                c = c.strip()
                column = _parse_column(c)
                if 'model' in column:
                    seeds.append(column)
            #
            row.append(column)
        #
        rows.append(row)
    #
    return rows, seeds
