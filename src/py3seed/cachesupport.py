# -*- coding: utf-8 -*-
"""
    cachesupport
    ~~~~~~~~~~~~~~

    Models in cache.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2022/9/14
"""
import inflection

from . import DataError
from .model import BaseModel
from .utils import Pagination

# {model_name:[dict]}
# Note: Do no store model object directly, as it may cause concurrent accessing issue
CACHES = {}


class CacheModel(BaseModel):
    """ Model in cache. """

    # id field definition
    __id_name__ = 'id'
    __id_type__ = int

    # id field
    id: int = None

    @classmethod
    def get_collection(cls, **kwargs):
        collection_name = inflection.pluralize(cls.__name__.lower())
        if collection_name not in CACHES:
            CACHES[collection_name] = []
        #
        return CACHES[collection_name]

    @classmethod
    def match_record(cls, record, filter_):
        """ Check if record match the filter. """
        #
        if not filter_:
            return True
        #
        match = True
        for field, condition in filter_.items():
            value = record.get(field)
            if isinstance(condition, dict):
                if '$in' in condition:
                    match = value in condition['$in']  # e.g, team.members -> user.team, then team.members = User.find({id: {$in: self.members_ids}})
                elif '$regex' in condition:
                    if isinstance(value, str):
                        match = condition['$regex'].match(value)  # e.g, Team.find({phone: {$regex: re.compile('^138')}})
                    else:
                        match = False
                else:
                    raise NotImplementedError(f'UNSUPPORTED condition: {condition}')
            else:
                if isinstance(value, list):
                    match = condition in value  # e.g, user.team -> team.members, then team.members = User.find({team_id: self.id})
                else:
                    match = value == condition  # e.g, user.team -> team.members, then user.team = Team.find({id: self.team_id})
        #
        return match

    @classmethod
    def find(cls, filter_=None, **kwargs):
        """ Find many records from cache.

        :param filter_: in mongodb's format, e.g, {name:xxx} or {id:{$in:[]}}
        """
        collection = cls.get_collection(**kwargs)
        records = [record for record in collection if cls.match_record(record, filter_)]
        # sort, [(field, order)], order ASCENDING = 1, order DESCENDING = -1
        if 'sort' in kwargs:
            sort = kwargs['sort']
            if len(sort) > 1:
                raise NotImplementedError(f'UNSUPPORTED sort: {sort}')
            #
            field, order = sort[0]
            records.sort(key=lambda x: x.get(field), reverse=(True if order == -1 else False))
        # pagination
        if 'skip' in kwargs:
            records = records[kwargs['skip']:kwargs['skip'] + kwargs['limit']]
        #
        return [cls(r) for r in records]

    @classmethod
    def count(cls, filter_=None, **kwargs):
        """ Count reconds. """
        collection = cls.get_collection(**kwargs)
        records = [record for record in collection if cls.match_record(record, filter_)]
        return len(records)

    @classmethod
    def find_one(cls, filter_or_id, **kwargs):
        """ Get a single record. """
        collection = cls.get_collection(**kwargs)
        #
        if filter_or_id is None:
            return None
        #
        if isinstance(filter_or_id, dict):
            records = [record for record in collection if cls.match_record(record, filter_or_id)]
        else:
            records = [record for record in collection if record['id'] == filter_or_id]
        #
        return cls(records[0]) if records else None

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
        filter_.update({'id': {'$in': ids}})
        #
        records = cls.find(filter_, *args, **kwargs)
        records.sort(key=lambda i: ids.index(i.id))
        #
        return records

    @classmethod
    def search(cls, filter_=None, page=1, per_page=20, max_page=-1, **kwargs):
        """ Search models and return records and pagination. """
        count = cls.count(filter_)
        if max_page > 0:
            limit = per_page * max_page
            if count > limit:
                count = limit
        start = (page - 1) * per_page
        records = cls.find(filter_, skip=start, limit=per_page, **kwargs)
        pagination = Pagination(page, per_page, count)
        return records, pagination

    @classmethod
    def delete_many(cls, filter_=None, **kwargs):
        collection = cls.get_collection(**kwargs)
        indexes = [index for index, record in enumerate(collection) if cls.match_record(record, filter_)]
        for index in indexes:
            del collection[index]
        #
        return True

    #
    #
    # Instance level methods
    #
    #

    def save(self, insert_with_id=False, **kwargs):
        """ Save model into cache. """
        errors = self.validate()
        if errors:
            raise DataError(f'It is an illegal {self.__class__.__name__} with errors, {errors}')
        #
        collection = self.get_collection(**kwargs)
        if insert_with_id or not self.id:
            # get the max id, start from 1
            self.id = max(list(map(lambda x: x['id'], collection)) or [0]) + 1
            collection.append(self.dict())
            return True
        else:
            indexes = [index for index, record in enumerate(collection) if record['id'] == self.id]
            if indexes:
                collection[indexes[0]] = self.dict()
                return True
            else:
                return False

    def delete(self, **kwargs):
        """ Delete self form cache. """
        collection = self.get_collection(**kwargs)
        indexes = [index for index, record in enumerate(collection) if record['id'] == self.id]
        if indexes:
            del collection[indexes[0]]
            return True
        else:
            return False
