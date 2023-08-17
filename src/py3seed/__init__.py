# -*- coding: utf-8 -*-
"""
    __init__.py
    ~~~~~~~~~~~~~~

    Package py3seed.

    :copyright: (c) 2020 by weiminfeng.
    :date: 2021/8/10
"""

import importlib_metadata

from .error import SeedError, SchemaError, DataError, DatabaseError, PathError, LayoutError, TemplateError
from .model import SimpleEnumMeta, SimpleEnum, Format, Comparator, Ownership, DATETIME_FORMAT, ModelJSONEncoder, \
    ModelField, RelationField, BaseModel
from .admin import register, registered_models
from .utils import Pagination
from .websupport import populate_model, populate_search, ModelJSONProvider
from .cachesupport import CacheModel
from .mongosupport import MongoModel, connect

metadata = importlib_metadata.metadata("py3seed")
__version__ = metadata["version"]
