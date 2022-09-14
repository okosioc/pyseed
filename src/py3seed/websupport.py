# -*- coding: utf-8 -*-
"""
    websupport
    ~~~~~~~~~~~~~~

    Web utils.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2022/9/14
"""
import re
from datetime import datetime

import inflection

from py3seed import Comparator, SimpleEnumMeta

# Valid datetime formats
_valid_formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d']


def _multidict_decode(md, dict_char='.', list_char='-'):
    """ Decode a multi-dict into a nested dict. """
    result = {}
    dicts_to_sort = set()
    for key, value in md.items():
        # Split keys into tokens by dict_char and list_char
        keys = _normalized_path(key).split(dict_char)
        new_keys = []
        for k in keys:
            if list_char in k:
                list_tokens = k.split(list_char)
                # For list tokens, the 1st one should always be field name, the latter ones are indexes
                for i in range(len(list_tokens)):
                    if list_tokens[i].isdigit():
                        new_keys.append(int(list_tokens[i]))
                    else:
                        new_keys.append(list_tokens[i])
                    if i < len(list_tokens) - 1:
                        dicts_to_sort.add(tuple(new_keys))
            else:
                new_keys.append(k)

        # Create inner dicts, lists are also initialized as dicts
        place = result
        for i in range(len(new_keys) - 1):
            try:
                if not isinstance(place[new_keys[i]], dict):
                    place[new_keys[i]] = {None: place[new_keys[i]]}
                place = place[new_keys[i]]
            except KeyError:
                place[new_keys[i]] = {}
                place = place[new_keys[i]]

        # Fill the contents
        if new_keys[-1] in place:
            if isinstance(place[new_keys[-1]], dict):
                place[new_keys[-1]][None] = value
            elif isinstance(place[new_keys[-1]], list):
                if isinstance(value, list):
                    place[new_keys[-1]].extend(value)
                else:
                    place[new_keys[-1]].append(value)
            else:
                if isinstance(value, list):
                    place[new_keys[-1]] = [place[new_keys[-1]]]
                    place[new_keys[-1]].extend(value)
                else:
                    place[new_keys[-1]] = [place[new_keys[-1]], value]
        else:
            place[new_keys[-1]] = value

    # Convert sorted dict to list
    to_sort_list = sorted(dicts_to_sort, key=len, reverse=True)
    for key in to_sort_list:
        to_sort = result
        source = None
        last_key = None
        for sub_key in key:
            source = to_sort
            last_key = sub_key
            to_sort = to_sort[sub_key]
        if None in to_sort:
            none_values = [(0, x) for x in to_sort.pop(None)]
            none_values.extend(iter(to_sort.items()))
            to_sort = none_values
        else:
            to_sort = iter(to_sort.items())

        to_sort = [x[1] for x in sorted(to_sort, key=_sort_key)]
        source[last_key] = to_sort

    return result


def _sort_key(item):
    """ Robust sort key that sorts items with invalid keys last.
    This is used to make sorting behave the same across Python 2 and 3.
    """
    key = item[0]
    return not isinstance(key, int), key


def populate_model(multidict, model_cls, set_default=True):
    """ Create a model instance from a multidict.
    This is necessary because some HTML form elements pass multiple values for the same key.

    :param multidict: multiple values for the same key, e.g, MultiDict([('a', 'b'), ('a', 'c')])
    """
    d = {}
    model_prefix = model_cls.__name__.lower() + '.'  # demouser.name
    model_prefix_underscore = inflection.underscore(model_cls.__name__) + '.'  # demo_user.name
    for key, value in multidict.items():
        # NOTE: Blank string skipped
        if not value:
            continue
        # Only process the keys with leading model.
        if key.startswith(model_prefix):
            key = key[len(model_prefix):]
        elif key.startswith(model_prefix_underscore):
            key = key[len(model_prefix_underscore):]
        else:
            continue
        #
        t = model_cls.get_type(key)
        if isinstance(value, list):
            converted_value = [convert_from_string(v, t) for v in value if v]
        else:
            converted_value = convert_from_string(value, t)
        #
        d[key] = converted_value
    #
    d = _multidict_decode(d)
    return model_cls(d)


def populate_search(multidict, model_cls):
    """ Create a condition from search query.

    :returns: search - return to page, condition - send to pymongo for search
    """
    search, condition = {}, {}
    for k, v in multidict.items():
        if not k.startswith('search.') or not v:
            continue
        # Remove search. from k
        k = k.replace('search.', '')
        v = v.strip()
        search[k] = v
        # Set default comparator
        c = Comparator.EQ
        if '__' in k:
            k, c = k.split('__')
        #
        t = model_cls.get_type(k)
        if Comparator.EQ == c:
            cond = convert_from_string(v, t)
        elif Comparator.IN == c or Comparator.NIN == c:
            cond = {'$%s' % c: [convert_from_string(vv, t) for vv in v]}
        elif Comparator.LIKE == c:
            # In order to use index, we only support starting string search here
            # https://docs.mongodb.com/manual/reference/operator/query/regex/#index-use
            regx = re.compile('^%s' % re.escape(v))
            cond = {'$regex': regx}
        else:
            cond = {'$%s' % c: convert_from_string(v, t)}
        #
        if k not in condition:
            condition[k] = cond
        else:
            condition[k].update(cond)
    #
    return search, condition


def _normalized_path(path, list_char='-'):
    """ Change [] -> - for easier processing.

    e.g, user.roles[0] -> user.roles-0
    """
    return path.replace('[', list_char).replace(']', '')


class DefaultTypeConverter(object):
    """ Convert string values from html request into typed. """

    def _convert_from_string(self, string_value, type):
        try:
            return type(string_value)
        except ValueError:
            raise ValueError("can not convert %s to %s" % (string_value, type.__name__))


class BoolConverter(DefaultTypeConverter):
    """ str -> bool """

    def _convert_from_string(self, string_value, type):
        return string_value.strip().lower() in ("yes", "true")


class DatetimeConverter(DefaultTypeConverter):
    """ str -> datetime """

    def _convert_from_string(self, string_value, type):
        for fmt in _valid_formats:
            try:
                return datetime.strptime(string_value, fmt)
            except ValueError:
                pass
        raise ValueError("can not convert %s to %s" % (string_value, type.__name__))


type_converters = {
    bool: BoolConverter(),
    datetime: DatetimeConverter(),
    None: DefaultTypeConverter(),  # Default converter
}


def convert_from_string(string_value, t):
    if isinstance(t, SimpleEnumMeta):
        t = t.type
    if isinstance(string_value, t):
        return string_value
    #
    if t in type_converters:
        converter = type_converters[t]
    else:
        converter = type_converters[None]
    #
    return converter._convert_from_string(string_value, t)
