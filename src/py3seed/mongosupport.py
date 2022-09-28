# -*- coding: utf-8 -*-
"""
    mongosupport
    ~~~~~~~~~~~~~~

    Model mappings for MongoDB.

    :copyright: (c) 2019 by weiminfeng.
    :date: 2019/12/15
"""
from copy import deepcopy

import pymongo
from bson import ObjectId
from pymongo import MongoClient, uri_parser, ReadPreference, WriteConcern
from pymongo.cursor import Cursor as PyMongoCursor

from .error import DatabaseError, DataError
from .model import BaseModel
from .utils import Pagination

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
    # Specify the name of the collection, or using the plural of the model's class name
    __collection_name__ = None

    # MongoDB alias, use it to support multi database
    # if None DEFAULT_CONNECTION_NAME
    __db_alias__ = None

    # id field definition
    __id_name__ = '_id'
    __id_type__ = ObjectId

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
            collection_name = cls.__collection_name__ if cls.__collection_name__ else (cls.__name__.lower() + 's')
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
            #
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
    def find_one(cls, filter_or_id, *args, **kwargs):
        """ Get a single model.

        https://pymongo.readthedocs.io/en/stable/api/pymongo/collection.html#pymongo.collection.Collection.find_one
        """
        collection = cls.get_collection(**kwargs)
        # If condition is None, pymongo will return the first document from collection, this may cause unexpected problems
        # e.g,
        # We would link to fetch a related user using User.find_one(self.uid), if uid is None, it is expected to return None.
        # If you would like to return a single user, use {} as condition, i.e, User.find_one({})
        if filter_or_id is None:
            return None
        #
        doc = collection.find_one(filter_or_id, *args, **kwargs)
        if doc:
            return cls(doc)
        else:
            return None

    @classmethod
    def find_one_and_update(cls, filter_or_id, update, *args, **kwargs):
        collection = cls.get_collection(**kwargs)
        if filter_or_id is None:
            return None
        #
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
    def search(cls, filter_=None, page=1, per_page=20, max_page=-1, **kwargs):
        """ Search models and return records and pagination. """
        count = cls.count(filter_)
        if max_page > 0:
            limit = per_page * max_page
            if count > limit:
                count = limit
        start = (page - 1) * per_page
        records = list(cls.find(filter_, skip=start, limit=per_page, **kwargs))
        pagination = Pagination(page, per_page, count)
        return records, pagination

    @classmethod
    def find_by_ids(cls, ids, *args, **kwargs):
        """ Find many models by multi ObjectIds. """
        #
        if not ids:
            return []
        #
        filter_ = {}
        if 'filter' in kwargs:
            filter_.update(kwargs.pop('filter'))
        elif len(args) > 0:
            filter_.update(args.pop(0))  # The first args should be filter format, i.e, {}
        #
        filter_.update({'_id': {'$in': ids}})
        #
        records = list(cls.find(filter_, *args, **kwargs))
        records.sort(key=lambda i: ids.index(i._id))
        #
        return records

    @classmethod
    def find_by_id(cls, id_, *args, **kwargs):
        """ Find one model by id. """
        collection = cls.get_collection(**kwargs)
        # If condition is None, pymongo will return the first document from collection, this may cause unexpected problems,
        if id_ is None:
            return None
        #
        doc = collection.find_one(id_, *args, **kwargs)
        if doc:
            return cls(doc)
        else:
            return None

    @classmethod
    def count(cls, filter_=None, **kwargs):
        """ Count reconds. """
        collection = cls.get_collection(**kwargs)
        if filter_:
            return collection.count_documents(filter_, **kwargs)
        else:
            return collection.estimated_document_count(**kwargs)

    @classmethod
    def replace_one(cls, filter_, replacement, *args, **kwargs):
        """ Please note we do not apply validation here. """
        collection = cls.get_collection(**kwargs)
        # UpdateResult
        return collection.replace_one(filter_, replacement, *args, **kwargs)

    @classmethod
    def update_one(cls, filter_, update, *args, **kwargs):
        """ Please note we do not apply validation here. """
        collection = cls.get_collection(**kwargs)
        # UpdateResult
        return collection.update_one(filter_, update, *args, **kwargs)

    @classmethod
    def update_many(cls, filter_, update, *args, **kwargs):
        """ Please note we do not apply validation here. """
        collection = cls.get_collection(**kwargs)
        # UpdateResult
        return collection.update_many(filter_, update, *args, **kwargs)

    @classmethod
    def delete_one(cls, filter_, **kwargs):
        collection = cls.get_collection(**kwargs)
        # DeleteResult
        return collection.delete_one(filter_)

    @classmethod
    def delete_many(cls, filter_, **kwargs):
        collection = cls.get_collection(**kwargs)
        # DeleteResult
        return collection.delete_many(filter_)

    @classmethod
    def aggregate(cls, pipeline, **kwargs):
        """ Aggr.

        https://pymongo.readthedocs.io/en/stable/api/pymongo/collection.html#pymongo.collection.Collection.aggregate
        """
        collection = cls.get_collection(**kwargs)
        return collection.aggregate(pipeline, **kwargs)

    @classmethod
    def distinct(cls, key, filter_=None, **kwargs):
        collection = cls.get_collection(**kwargs)
        return collection.distinct(key, filter_, **kwargs)

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
