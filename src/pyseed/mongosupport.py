# -*- coding: utf-8 -*-
"""
    mongosupport
    ~~~~~~~~~~~~~~

    Model mappings for MongoDB.

    :copyright: (c) 2019 by weiminfeng.
    :date: 2019/12/15
"""
import math
import re
from copy import deepcopy
from datetime import datetime

import pymongo
from bson import ObjectId
from pymongo import MongoClient, uri_parser, ReadPreference, WriteConcern
from pymongo.cursor import Cursor as PyMongoCursor

from .error import DatabaseError, DataError
from .model import BaseModel, Comparator, SimpleEnumMeta

# ----------------------------------------------------------------------------------------------------------------------
# Connection - Support multiple database
#

DEFAULT_CONNECTION_NAME = 'default'

# {alias:setting parameters dict}
_connection_settings = {}
# {alias:instance of pymongo.MongoClient}
_connections = {}
# {alias:database of pymongo.Database}
_dbs = {}

# Valid datetime formats
_valid_formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d']


def connect(uri, alias=DEFAULT_CONNECTION_NAME, **kwargs):
    """ Connect to database by uri, database name will be extracted from the uri and used for different MongoClient. """
    uri_dict = uri_parser.parse_uri(uri)
    name = uri_dict.get('database')  # Database name
    username = uri_dict.get('username', None)
    password = uri_dict.get('password', None)

    global _connections
    if alias not in _connections:
        _register_connection(alias, name, uri, username, password, **kwargs)
    return _get_connection(alias)


def disconnect(alias=DEFAULT_CONNECTION_NAME):
    """ Disconnect from a database. """
    global _connections
    global _dbs

    if alias in _connections:
        _get_connection(alias).close()
        del _connections[alias]
    if alias in _dbs:
        del _dbs[alias]


def _register_connection(alias, name, uri, username=None, password=None,
                         read_preference=ReadPreference.PRIMARY,
                         authentication_source=None,
                         **kwargs):
    """ Register connection uri. """
    global _connection_settings
    conn_settings = {
        'name': name,
        'host': uri,
        'read_preference': read_preference,
        'username': username,
        'password': password,
        'authentication_source': authentication_source
    }
    conn_settings.update(kwargs)
    _connection_settings[alias] = conn_settings


def _get_connection(alias=DEFAULT_CONNECTION_NAME, reconnect=False):
    """ Get connection. """
    global _connections

    if reconnect:
        disconnect(alias)

    if alias not in _connections:
        if alias not in _connection_settings:
            msg = 'Connection with alias "%s" has not been defined' % alias
            if alias == DEFAULT_CONNECTION_NAME:
                msg = 'You have not defined a default connection'
            raise DatabaseError(msg)
        # Check existing connections that can be shared for current alias
        conn_settings = _connection_settings[alias].copy()
        conn_settings.pop('name', None)
        conn_settings.pop('username', None)
        conn_settings.pop('password', None)
        conn_settings.pop('authentication_source', None)

        """
        Every MongoClient instance has a built-in connection pool.
        The client instance opens one additional socket per server for monitoring the server’s state.
        """
        connection_class = MongoClient

        try:
            connection = None
            # Check for shared connections
            connection_settings_iterator = (
                (db_alias, settings.copy()) for db_alias, settings in _connection_settings.items())
            for db_alias, connection_settings in connection_settings_iterator:
                connection_settings.pop('name', None)
                connection_settings.pop('username', None)
                connection_settings.pop('password', None)
                connection_settings.pop('authentication_source', None)
                if conn_settings == connection_settings and _connections.get(db_alias, None):
                    connection = _connections[db_alias]
                    break

            _connections[alias] = connection if connection else connection_class(**conn_settings)
        except Exception as e:
            raise DatabaseError("Cannot connect to database %s :\n%s" % (alias, e))
    return _connections[alias]


def get_db(alias=DEFAULT_CONNECTION_NAME, reconnect=False):
    """ Get database """
    global _dbs

    if reconnect:
        disconnect(alias)

    if alias not in _dbs:
        conn = _get_connection(alias)
        conn_settings = _connection_settings[alias]
        db = conn[conn_settings['name']]
        # Authenticate if necessary
        if conn_settings['username'] and conn_settings['password']:
            db.authenticate(conn_settings['username'],
                            conn_settings['password'],
                            source=conn_settings['authentication_source'])
        _dbs[alias] = db
    return _dbs[alias]


# ----------------------------------------------------------------------------------------------------------------------
# MongoModel
#

class MongoModel(BaseModel):
    """ Model with mongo support. """
    # MongoDB indexes definition
    # e.g,
    # __indexes__ = [{'fields': ['email'], 'unique': True}]
    # __indexes__ = [{'fields': [('geo':'2d')]}]
    __indexes__ = []

    # pymongo.Collection, can use it to invode pymongo's methods directly
    # https://api.mongodb.com/python/current/tutorial.html
    __collection__ = None

    # MongoDB alias, use it to support multi database
    # if None DEFAULT_CONNECTION_NAME
    __db_alias__ = None

    # Mongo ID field
    _id: ObjectId = None

    #
    #
    # Class level pymongo api
    #
    #

    @classmethod
    def get_collection(cls, **kwargs):
        """ Returns the collection for the model. """
        if kwargs.get('refresh', False) or cls.__collection__ is None:
            #
            db = get_db(cls.__db_alias__ if cls.__db_alias__ else DEFAULT_CONNECTION_NAME)
            # You can specify read_preference/write_concern when invoking this method
            read_preference = kwargs.get("read_preference") or ReadPreference.PRIMARY
            write_concern = kwargs.get("write_concern") or WriteConcern(w=1)
            # Use model name + s as connection name, so please make sure model name is unique
            collection_name = cls.__name__.lower() + 's'
            cls.__collection__ = db[collection_name].with_options(read_preference=read_preference,
                                                                  write_concern=write_concern)
            # Try to create index when getting collection
            # https://docs.mongodb.com/getting-started/python/indexes/
            cls._create_indexes(cls.__collection__)
        #
        return cls.__collection__

    @classmethod
    def _create_indexes(cls, collection):
        """ Create indexes. """
        # print("Try to create index for %s" % cls.__name__)
        for index in deepcopy(cls.__indexes__):
            unique = False
            if 'unique' in index:
                unique = index.pop('unique')

            given_fields = index.pop("fields", list())
            if isinstance(given_fields, str):
                fields = [(given_fields, pymongo.ASCENDING)]
            else:
                fields = []
                for field in given_fields:
                    if isinstance(field, str):
                        field = (field, pymongo.ASCENDING)
                    fields.append(field)

            # print('Creating index for {}'.format(str(given_fields)))
            collection.create_index(fields, unique=unique, **index)

    @classmethod
    def insert_one(cls, doc, *args, **kwargs):
        """ Please note we do not apply validation here. """
        collection = cls.get_collection(**kwargs)
        # InsertOneResult
        return collection.insert_one(doc, *args, **kwargs)

    @classmethod
    def insert_many(cls, docs, *args, **kwargs):
        """ Please note we do not apply validation here. """
        collection = cls.get_collection(**kwargs)
        # InsertManyResult
        return collection.insert_many(docs, *args, **kwargs)

    @classmethod
    def find_one(cls, filter_or_id=None, *args, **kwargs):
        collection = cls.get_collection(**kwargs)
        doc = collection.find_one(filter_or_id, *args, **kwargs)
        if doc:
            return cls(doc)
        else:
            return None

    @classmethod
    def find_one_and_update(cls, filter_or_id, update, *args, **kwargs):
        collection = cls.get_collection(**kwargs)
        doc = collection.find_one_and_update(filter_or_id, update, *args, **kwargs)
        if doc:
            return cls(doc)
        else:
            return None

    @classmethod
    def find(cls, *args, **kwargs):
        """ Find many models and return cursor.

        https://pymongo.readthedocs.io/en/stable/api/pymongo/collection.html#pymongo.collection.Collection.find
        """
        collection = cls.get_collection(**kwargs)
        return ModelCursor(cls, collection, *args, **kwargs)

    @classmethod
    def search(cls, filter=None, page=1, per_page=20, max_page=-1, **kwargs):
        """ Search models and return records and pagination. """
        count = cls.count(filter)
        if max_page > 0:
            limit = per_page * max_page
            if count > limit:
                count = limit
        start = (page - 1) * per_page
        records = list(cls.find(filter, skip=start, limit=per_page, **kwargs))
        pagination = Pagination(page, per_page, count)
        return records, pagination

    @classmethod
    def find_by_ids(cls, ids, *args, **kwargs):
        """ Find many models by multi ObjectIds. """
        filter = {}
        if 'filter' in kwargs:
            filter.update(kwargs.pop('filter'))
        elif len(args) > 0:
            filter.update(args.pop(0))
        filter.update({'_id': {'$in': ids}})

        records = list(cls.find(filter, *args, **kwargs))
        records.sort(key=lambda i: ids.index(i._id))
        return records

    @classmethod
    def count(cls, filter=None, **kwargs):
        collection = cls.get_collection(**kwargs)
        if filter:
            return collection.count_documents(filter, **kwargs)
        else:
            return collection.estimated_document_count(**kwargs)

    @classmethod
    def replace_one(cls, filter, replacement, *args, **kwargs):
        """ Please note we do not apply validation here. """
        collection = cls.get_collection(**kwargs)
        # UpdateResult
        return collection.replace_one(filter, replacement, *args, **kwargs)

    @classmethod
    def update_one(cls, filter, update, *args, **kwargs):
        """ Please note we do not apply validation here. """
        collection = cls.get_collection(**kwargs)
        # UpdateResult
        return collection.update_one(filter, update, *args, **kwargs)

    @classmethod
    def update_many(cls, filter, update, *args, **kwargs):
        """ Please note we do not apply validation here. """
        collection = cls.get_collection(**kwargs)
        # UpdateResult
        return collection.update_many(filter, update, *args, **kwargs)

    @classmethod
    def delete_one(cls, filter, **kwargs):
        collection = cls.get_collection(**kwargs)
        # DeleteResult
        return collection.delete_one(filter)

    @classmethod
    def delete_many(cls, filter, **kwargs):
        collection = cls.get_collection(**kwargs)
        # DeleteResult
        return collection.delete_many(filter)

    @classmethod
    def aggregate(cls, pipeline, **kwargs):
        """ Aggr.

        https://pymongo.readthedocs.io/en/stable/api/pymongo/collection.html#pymongo.collection.Collection.aggregate
        """
        collection = cls.get_collection(**kwargs)
        return collection.aggregate(pipeline, **kwargs)

    @classmethod
    def distinct(cls, key, filter=None, **kwargs):
        collection = cls.get_collection(**kwargs)
        return collection.distinct(key, filter, **kwargs)

    @classmethod
    def group(cls, key, condition, initial, reduce, finalize=None, **kwargs):
        collection = cls.get_collection(**kwargs)
        return collection.group(key, condition, initial, reduce, finalize, **kwargs)

    #
    #
    # Instance level pymongo api
    #
    #

    def save(self, insert_with_id=False, **kwargs):
        """ Save model into database. """
        errors = self.validate()
        if errors:
            raise DataError(f'It is an illegal {self.__class__.__name__} with errors, {errors}')
        #
        collection = self.get_collection(**kwargs)
        if insert_with_id or not self._id:
            if self._id:
                delattr(self, '_id')
            # InsertOneResult
            result = collection.insert_one(self.dict())
            self._id = result.inserted_id
            return result
        else:
            # UpdateResult
            return collection.replace_one({'_id': self._id}, self.dict())

    def delete(self, **kwargs):
        collection = self.get_collection(**kwargs)
        # DeleteResult
        return collection.delete_one({'_id': self._id})


# ----------------------------------------------------------------------------------------------------------------------
# Cursor - Wrap pymongo.cursor to return mongosupport objects
#

class ModelCursor(PyMongoCursor):
    def __init__(self, model_class, collection, *args, **kwargs):
        self.model_class = model_class
        super(ModelCursor, self).__init__(collection, *args, **kwargs)

    def next(self):
        return self.model_class(super(ModelCursor, self).next())

    def __next__(self):
        return self.model_class(super(ModelCursor, self).__next__())

    def __getitem__(self, index):
        if isinstance(index, slice):
            return super(ModelCursor, self).__getitem__(index)
        else:
            return self.model_class(super(ModelCursor, self).__getitem__(index))


# ----------------------------------------------------------------------------------------------------------------------
# Pagination
#

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


# ----------------------------------------------------------------------------------------------------------------------
# Html request processing
#

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
    model_prefix = model_cls.__name__.lower() + '.'
    for key, value in multidict.items():
        # NOTE: Blank string skipped
        if not value:
            continue
        # Only process the keys with leading model.
        if key.startswith(model_prefix):
            key = key[len(model_prefix):]
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
    return converter._convert_from_string(string_value, t)
