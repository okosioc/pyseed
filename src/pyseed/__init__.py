# -*- coding: utf-8 -*-
"""
    __init__.py
    ~~~~~~~~~~~~~~

    Package pyseed.

    :copyright: (c) 2020 by weiminfeng.
    :date: 2021/8/10
"""

import importlib_metadata

from .error import SeedError, SchemaError, DataError, DatabaseError, PathError
from .model import SimpleEnumMeta, SimpleEnum, Format, Comparator, DATETIME_FORMAT, ModelJSONEncoder, \
    ModelField, BaseModel, relation
from .admin import register, registered_models
from .mongosupport import MongoModel, connect, populate_model, populate_search

metadata = importlib_metadata.metadata("py3seed")
__version__ = metadata["version"]
