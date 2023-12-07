# -*- coding: utf-8 -*-
"""
    websupport
    ~~~~~~~~~~~~~~

    Web utils.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2022/9/14
"""
import json
import re

from datetime import datetime
from typing import get_origin, get_args

from flask.json.provider import DefaultJSONProvider
from py3seed import Comparator, SimpleEnumMeta, inflection, ModelJSONEncoder

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


def populate_model(multidict, model_cls):
    """ Create a model instance from a multidict.
    This is necessary because some HTML form elements pass multiple values for the same key.

    :param multidict: werkzeug.datastructures.MultiDict
    :param model_cls: model class to be populated
    """
    d = {}
    model_prefix = model_cls.__name__.lower() + '.'  # demouser.name
    model_prefix_underscore = inflection.underscore(model_cls.__name__) + '.'  # demo_user.name
    # NOTE: MultiDict.items() will only return the first value for the same key
    # MultiDict.lists() will return all values as list for the same key
    # e.g, MultiDict([('a', 'b'), ('a', 'c'), ('1', '2'), ('!', None)])
    # md.items() = [('a', 'b'), ('1', '2'), ('!', None)]
    # md.lists() = [('a', ['b', 'c']), ('1', ['2']), ('!', [None])]
    for key, values in multidict.lists():
        # Only process the keys with leading model.
        if key.startswith(model_prefix):
            key = key[len(model_prefix):]
        elif key.startswith(model_prefix_underscore):
            key = key[len(model_prefix_underscore):]
        else:
            continue
        # Filter blank values in value
        values = [v.strip() for v in values if v]
        if not values:
            continue
        #
        type_ = model_cls.get_type(key)
        origin = get_origin(type_)
        if origin is list:
            type_ = get_args(type_)[0]
            converted_value = [convert_from_string(v, type_) for v in values]
        else:
            value = values[0]  # NOTE: Only the first value is used as field type is not a list
            converted_value = convert_from_string(value, type_)
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
    search_prefix = 'search.'
    for key, values in multidict.lists():
        # Only process the keys with leading search.
        if key.startswith(search_prefix):
            key = key.replace(search_prefix, '')
        else:
            continue
        # Filter blank values in value
        values = [v.strip() for v in values if v]
        if not values:
            continue
        # Set value to search for page rendering
        search[key] = values if len(values) > 1 else values[0]
        # Set default comparator
        comparator = Comparator.EQ
        if '__' in key:
            field, comparator = key.split('__')
        else:
            field = key
        # Convert value according to field type
        type_ = model_cls.get_type(field)
        # If field type is a list, please read mongo's document firstly, https://www.mongodb.com/docs/manual/tutorial/query-arrays/
        # e.g, post.tags is List[str]
        # - search condition {tags: 'tech'} will filter the whose tags contains tech
        # - search condition {tags: {$in: ['tech', 'life']}} will filter whose tags contains tech or life
        # - search condition {tags: ['tech', 'life']} will filter whose tags is same as [tech, life]
        # We always do not want to match extractly the whole list field, so we need inner type to build condition
        origin = get_origin(type_)
        if origin is list:
            type_ = get_args(type_)[0]
        # Build condition according to comparator
        if Comparator.EQ == comparator:
            if len(values) == 1:
                cond = convert_from_string(values[0], type_)
            else:
                cond = {'$in': [convert_from_string(v, type_) for v in values]}
        elif Comparator.IN == comparator or Comparator.NIN == comparator:
            cond = {'$%s' % comparator: [convert_from_string(v, type_) for v in values]}
        elif Comparator.LIKE == comparator:
            value = values[0]
            # NOTE: Performance issue for huge collection, as $regex is not index friendly
            # Use case-sensitive prefix expression can use mongodb index, regx = re.compile('^%s' % re.escape(v))
            # https://docs.mongodb.com/manual/reference/operator/query/regex/#index-use
            regx = re.compile('.*%s.*' % re.escape(value), re.IGNORECASE)
            cond = {'$regex': regx}
        else:
            value = values[0]
            cond = {'$%s' % comparator: convert_from_string(value, type_)}
        #
        if field not in condition:
            condition[field] = cond
        else:
            condition[field].update(cond)
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


class ModelJSONProvider(DefaultJSONProvider):
    """ json_encode is removed from flask 2.3, instead you need to provide a json provider.

    https://flask.palletsprojects.com/en/2.3.x/api/#flask.Flask.json
    """

    def dumps(self, obj, **kwargs):
        return json.dumps(obj, **kwargs, cls=ModelJSONEncoder)

    def loads(self, s, **kwargs):
        return json.loads(s, **kwargs)
