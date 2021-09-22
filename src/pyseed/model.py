# -*- coding: utf-8 -*-
"""
    model
    ~~~~~~~~~~~~~~

    Model related.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/6/5
"""
import functools
import json
from abc import ABCMeta
from copy import deepcopy
from datetime import datetime
from typing import no_type_check, Dict, Type, Callable, get_origin, get_args, get_type_hints, Set, Any

from bson import ObjectId

from .error import SchemaError, DataError, PathError


# ----------------------------------------------------------------------------------------------------------------------
# Custom Types
#

class SimpleEnumMeta(type):
    """ Metaclass for SimpleEnum. """

    def __new__(mcs, name, bases, attrs):
        enum_class = type.__new__(mcs, name, bases, attrs)
        enum_class._member_dict_ = {}
        enum_class._title_dict_ = {}
        for k in attrs:
            if k.startswith('_'):
                continue
            #
            v = attrs[k]
            t = k.lower().capitalize()  # Enum names should always be more readable then values
            if isinstance(v, (list, tuple)):
                v, t = v
            enum_class._member_dict_[k] = v  # name -> value
            enum_class._title_dict_[k] = t  # name -> title
        # TODO: Check repeated names or values
        return enum_class

    def __getattribute__(cls, name):
        if not name.startswith('_') and name in cls._member_dict_:
            return cls._member_dict_[name]
        else:
            return object.__getattribute__(cls, name)

    def __getitem__(cls, name):
        return cls._member_dict_[name]

    def __iter__(cls):
        """ Returns all values. """
        return (cls._member_dict_[name] for name in cls._member_dict_)

    @property
    def __members__(cls):
        """ Returns all members name->value. """
        return cls._member_dict_

    def __len__(cls):
        return len(cls._member_dict_)

    def __repr__(cls):
        """ Return representation str. """
        return "<SimpleEnumMeta %r %s>" % (cls.__name__, list(cls))

    @property
    def type(cls):
        """ Get type of members, All members should be the same type. """
        return type(next(cls.__iter__(), None))

    def validate(cls, value):
        """ Validate if a value is defined in a simple enum class. """
        return value in cls._member_dict_.values()

    @property
    def titles(cls):
        """ Return value->title dict. """
        return {cls._member_dict_[name]: cls._title_dict_[name] for name in cls._member_dict_}

    def to_title(cls, value):
        """ Get title from value. """
        for k, v in cls._member_dict_.items():
            if v == value:
                return cls._title_dict_[k]
        #
        return None

    def from_title(cls, title):
        """ Get value from title. """
        for k, t in cls._title_dict_.items():
            if t == title:
                return cls._member_dict_[k]
        #
        return None


class SimpleEnum(object, metaclass=SimpleEnumMeta):
    """ Parent class for simple enum fields. """
    pass


class Format(SimpleEnum):
    """ Predefined available formats, which should be used to control ui or api generation.

    Below values are the same with OAS 3.0
    https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#data-types
    https://swagger.io/docs/specification/data-models/data-types/
    """
    DATETIME = 'datetime'  # Default format for datetime
    DATE = 'date'
    PASSWORD = 'password'
    BYTE = 'byte'
    # Below values are self-defined
    TEXT = 'text'  # Default format for str
    INT = 'int'  # Default format for int
    FLOAT = 'float'  # Default format for float
    SELECT = 'select'  # Default format for SimpleEnum
    BUTTONGROUP = 'buttongroup'
    TAG = 'tag'  # Tag input
    PASSWORD = 'password'
    TEXTAREA = 'textarea'
    RTE = 'rte'
    MARKDOWN = 'markdown'
    IMAGE = 'image'  # Image upload support
    AVATAR = 'avatar'  # User avatar
    FILE = 'file'  # File upload support
    IP = 'ip'
    OBJECTID = 'objectid'  # Default format for ObjectId
    CHECKBOX = 'checkbox'  # Default format for bool
    SWITCH = 'switch'
    # Below values are used for inner model/dict or list of model/dict
    LIST = 'list'  # Default format for List
    TAB = 'tab'
    TABLE = 'table'
    CARD = 'card'
    CAROUSEL = 'carousel'
    COLLAPSE = 'collapse'
    CASCADER = 'cascader'  # Cascade selection, i.e, List[str]
    LATLNG = 'latlng'  # LatLng chooser, i.e, List[float]


class Comparator(SimpleEnum):
    """ Predefined compartors, which should be used to control search conditions.

    These comparators are referred to https://docs.mongodb.com/manual/reference/operator/query-comparison/
    Just append $ to build a search.
    """
    EQ = 'eq'  # =
    NE = 'ne'  # !=
    GT = 'gt'  # >
    GTE = 'gte'  # >=
    LT = 'lt'  # <
    LTE = 'lte'  # <=
    IN = 'in'
    NIN = 'nin'
    LIKE = 'like'  # Need to convert this to regex


# ----------------------------------------------------------------------------------------------------------------------
# Constants
#

# Date format
DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'
DATETIME_FORMAT_SHORT = '%Y-%m-%d %H:%M:%S'

# Supported types for modal fields
# NOTE: These types are also used in form generation.
AUTHORIZED_TYPES = [
    bool,
    int,
    float,
    str,
    datetime,
    ObjectId,  # https://api.mongodb.com/python/current/api/bson/son.html
]


class UndefinedType:
    """ Undefined type. """

    def __repr__(self) -> str:
        return 'Undefined'

    def __reduce__(self) -> str:
        return 'Undefined'


Undefined = UndefinedType()


# ----------------------------------------------------------------------------------------------------------------------
# Conversions
#

class ModelJSONEncoder(json.JSONEncoder):
    """ Json encoder for model. """

    def default(self, o):
        """ Returns a serializable object for o. """
        if isinstance(o, ObjectId):
            return str(o)
        elif isinstance(o, datetime):
            return o.strftime(DATETIME_FORMAT)

        return json.JSONEncoder.default(self, o)


# ----------------------------------------------------------------------------------------------------------------------
# Validator
#

class Validator:
    """ Callable validator definition. """
    __slots__ = 'func', 'skip_on_failure'

    def __init__(
            self,
            func: Callable,
            skip_on_failure: bool = False,
    ):
        self.func = func
        self.skip_on_failure = skip_on_failure


# ----------------------------------------------------------------------------------------------------------------------
# Model field
#

class ModelField:
    """ Field definition for model. """
    __slots__ = (
        'name',
        'type',
        'default',
        'required',
        'format',
        'title',
        'description',
        'unit',
        'alias',
    )

    def __init__(self,
                 name: str = None, type_: Type = None,
                 default: Any = Undefined, required: bool = Undefined, format_: Format = None,
                 title: str = None, description: str = None, unit: str = None, alias: str = None) -> None:
        """ Init method.

        :param type_: annotaion for field, e.g, str or Dict[str, str] or List[Object]
        """
        self.name = name
        self.type = type_
        if default is Undefined:
            self.default = None
            self.required = True
        elif default is None:
            self.default = None
            self.required = False
        else:
            self.default = default
            self.required = True
        # Overwrite calcuated required if specified
        if required is not Undefined:
            self.required = required
        self.format = format_
        self.title = title
        self.description = description
        self.unit = unit
        self.alias = alias

    def __str__(self):
        return f'{self.name}/{self.type}/{self.default}/{self.required}/{self.format}'


# ----------------------------------------------------------------------------------------------------------------------
# Relation
#

class relation(object):
    """ Decorator on a method to tell that it is used to fetch related models.

    class Parrot:
        def __init__(self):
            self._voltage = 100
        @relation
        def voltage(self):
            return self._voltage

    p = Parrot()
    print(p.voltage)
    #=> 100

    Reference:
    https://docs.python.org/3/howto/descriptor.html#properties
    https://realpython.com/primer-on-python-decorators/#classes-as-decorators
    https://docs.python.org/3/reference/datamodel.html#object.__get__
    """

    def __init__(self, func):
        functools.update_wrapper(self, func)
        self.func = func

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self.func(obj)


# ----------------------------------------------------------------------------------------------------------------------
# Meta class
#

class ModelMeta(ABCMeta):
    """ Metaclass for model. """

    @no_type_check
    def __new__(mcs, name, bases, namespace, **kwargs):
        """ Create and return a new object. """
        fields: Dict[str, ModelField] = {}
        relations: Dict[str, relation] = {}

        # TODO: Support callable validators

        slots: Set[str] = namespace.get('__slots__', ())
        slots = {slots} if isinstance(slots, str) else set(slots)

        for base in reversed(bases):
            if issubclass(base, BaseModel) and base is not BaseModel:
                fields.update(deepcopy(base.__fields__))

        def _validate_annotation(field_name, field_type):
            """ Validate field definition."""
            # Validate if shadows a parent attribute
            for base in bases:
                if getattr(base, field_name, None):
                    raise SchemaError(f'{field_name}: {field_type} shadows a parent attribute')
            #
            origin = get_origin(field_type)
            # Simple, including built-in type, SimpleEnum or sub model
            if origin is None:
                _validate_simple_annotation(field_name, field_type)
            # Dict
            elif origin is dict:
                k_type, v_type = get_args(field_type)
                if k_type is not str:
                    raise SchemaError(f'{field_name}: {field_type} only support str keys')
                #
                _validate_simple_annotation(field_name, v_type)
            # List
            elif origin is list:
                l_type = get_args(field_type)[0]
                _validate_simple_annotation(field_name, l_type)
            else:
                raise SchemaError(f'{field_name}: {field_type} is not supported')

        def _validate_simple_annotation(field_name, field_type):
            """ Inner method to validate built-in types, SimpleEnums or sub models. """
            if isinstance(field_type, SimpleEnumMeta):
                enum_types = set()
                for member in field_type:
                    enum_types.add(type(member))
                    if type(member) not in AUTHORIZED_TYPES:
                        raise SchemaError(f'{field_name}: {field_type} is not an authorized type')
                if len(enum_types) == 0:
                    raise SchemaError(f'{field_name}: {field_type} has not defined any enum values')
                if len(enum_types) > 1:
                    raise SchemaError(f'{field_name}: {field_type} can not have more than one type')
            elif issubclass(field_type, BaseModel):
                for a_n, a_t in get_type_hints(field_type).items():
                    _validate_annotation(a_n, a_t)
            elif field_type not in AUTHORIZED_TYPES:
                raise SchemaError(f'{field_name}: {field_type} is not an authorized type')

        # Validation
        skips = set()
        if namespace.get('__qualname__') != 'BaseModel':
            # Annotations
            annotations = namespace.get('__annotations__', {})
            for ann_name, ann_type in annotations.items():
                # Skip
                if ann_name.startswith('__'):
                    skips.add(ann_name)
                    continue
                # Validate
                _validate_annotation(ann_name, ann_type)
                # Create model field
                field = ModelField(name=ann_name, type_=ann_type)
                value = namespace.get(ann_name, Undefined)
                # Field is required if undefined
                if value is Undefined:
                    field.default = None
                    field.required = True
                # Field is NOT required
                elif value is None:
                    field.default = None
                    field.required = False
                # Define a ModelField directly
                elif isinstance(value, ModelField):
                    # x6
                    field.default = value.default
                    field.required = value.required
                    field.format = value.format
                    field.title = value.title
                    field.description = value.description
                    field.unit = value.unit
                    field.alias = value.alias
                # Set default value
                else:
                    field.default = value
                    field.required = True
                # check default value type
                if field.default is not None:
                    if isinstance(ann_type, SimpleEnumMeta):
                        if not ann_type.validate(field.default):
                            raise SchemaError(f'{ann_name}: {ann_type} default value is invalid')
                    else:
                        # Skip if default is callable, e.g, datetime.now
                        if callable(field.default):
                            pass
                        elif isinstance(field.default, list):
                            pass
                        elif not isinstance(field.default, ann_type):
                            raise SchemaError(f'{ann_name}: {ann_type} default value is invalid')
                #
                fields[ann_name] = field
            #
            # Relations
            for attr in namespace:
                if isinstance(namespace.get(attr), relation):
                    relations[attr] = namespace.get(attr)

        # Create class
        exclude_from_namespace = fields.keys() | skips | relations.keys() | {'__slots__'}
        new_namespace = {
            '__fields__': fields,
            '__slots__': slots,
            '__relations__': relations,
            **{n: v for n, v in namespace.items() if n not in exclude_from_namespace},
        }
        cls = super().__new__(mcs, name, bases, new_namespace, **kwargs)
        return cls


class BaseModel(metaclass=ModelMeta):
    """ Base Model. """

    __slots__ = ('__dict__', '__fields_set__', '__errors__')
    __doc__ = ''

    # TODO: Validate below fields
    __searchables__ = []
    __columns__ = []
    __sortables__ = []
    __layout__ = None

    def __init__(self, *d: Dict[str, Any], **data: Any) -> None:
        """ Init.

        :param d: create model from dict
        :param **data: create model from kwargs
        """
        data_ = d[0] if d else data
        values, fields_set, errors = self.validate_data(data_)
        object.__setattr__(self, '__dict__', values)
        object.__setattr__(self, '__fields_set__', fields_set)
        object.__setattr__(self, '__errors__', errors)

    def validate(self):
        """ Validate self. """
        _, _, errors = self.validate_data(self.__dict__)
        object.__setattr__(self, '__errors__', errors)
        return errors

    @classmethod
    def validate_data(cls, data: Dict[str, Any]):
        """ Validate data against model.

        :param data: Inner sub models can be dict or model instance
        """
        values = {}
        fields_set = set()
        errors = []
        # Validate against schema
        # print(f'Validate {cls.__name__} with {data}')
        for field_name, field_type in cls.__fields__.items():
            field_value, field_errors = cls._validate_field(field_type, data.get(field_name, Undefined))
            if field_value is not Undefined:
                values[field_name] = field_value
                fields_set.add(field_name)
            if field_errors:
                errors.extend(field_errors)
        # Check if any non-defined field
        undefined_fields = set(data.keys()) - set(cls.__fields__.keys())
        if len(undefined_fields) > 0:
            errors.append(f'{cls.__name__}: Found undefined data fields, {undefined_fields}')
        #
        return values, fields_set, errors

    @classmethod
    def _validate_field(cls, field: ModelField, value: Any):
        """ Validate value against field. """
        field_errors = []
        # Undefined logic, check required and set default value
        if value is Undefined:
            if field.required:
                field_errors.append(DataError(f'{cls.__name__}.{field.name}: {field.type} is required'))
            #
            field_value = value
            if field.default is not None:
                if callable(field.default):
                    field_value = field.default()
                else:
                    field_value = field.default
        # Validate Logic, check value against field definition
        else:
            origin = get_origin(field.type)
            # Dict
            if origin is dict:
                if field.required and not value:
                    field_errors.append(DataError(f'{cls.__name__}.{field.name}: {field.type} is required'))
                #
                field_value = {}
                v_type = get_args(field.type)[1]
                for k, v_ in value.items():
                    if not isinstance(k, str):
                        field_errors.append(
                            DataError(f'{cls.__name__}.{field.name}: {field.type} only support str keys'))
                    #
                    type_value, type_errors = cls._validate_type(field, v_, v_type)
                    field_value[k] = type_value
                    if type_errors:
                        field_errors.extend(type_errors)
            # List
            elif origin is list:
                if field.required and not value:
                    field_errors.append(DataError(f'{cls.__name__}.{field.name}: {field.type} is required'))
                #
                field_value = []
                l_type = get_args(field.type)[0]
                for v_ in value:
                    type_value, type_errors = cls._validate_type(field, v_, l_type)
                    field_value.append(type_value)
                    if type_errors:
                        field_errors.extend(type_errors)
            # built-in type, SimpleEnum or sub model
            else:
                if field.required and value is None:
                    field_errors.append(DataError(f'{cls.__name__}.{field.name}: {field.type} is required'))
                #
                type_value, type_errors = cls._validate_type(field, value, field.type)
                field_value = type_value
                if type_errors:
                    field_errors.extend(type_errors)
        #
        # print(f'Validate field {field} with {value} -> {field_value} {field_errors}')
        return field_value, field_errors

    @classmethod
    def _validate_type(cls, field: ModelField, value: Any, type_: Type):
        """ Validate simple type, i.e, built-in type, SimpleEnum or sub model. """
        type_errors = []
        type_value = value
        #
        if type_value is not None:
            if isinstance(type_, SimpleEnumMeta):
                if not type_.validate(type_value):
                    type_errors.append(
                        DataError(f'{cls.__name__}.{field.name}: {field.type} has invalid value'))
            elif issubclass(type_, BaseModel):
                #  Value can be raw dict against sub model
                if isinstance(type_value, dict):
                    type_value = type_(**value)
                    if type_value.__errors__:
                        type_errors.extend(type_value.__errors__)
                # Value is instance of sub model
                else:
                    errors = type_value.validate()
                    if errors:
                        type_errors.extend(errors)
            elif not isinstance(type_value, type_):
                type_errors.append(DataError(f'{cls.__name__}.{field.name}: {field.type} only support {type_} value'))
        #
        return type_value, type_errors

    def __setattr__(self, name, value):
        self.__dict__[name] = value
        self.__fields_set__.add(name)

    def __getattr__(self, name):
        """ if the field name is predefined and referral model, create a model object first. """
        if name in self.__class__.__fields__:
            type_ = self.__class__.__fields__[name].type
            origin = get_origin(type_)
            v = None
            if origin is None:
                if issubclass(type_, BaseModel):
                    v = type_()
            elif origin is list:
                v = []
            elif origin is dict:
                v = {}
            #
            if v is not None:
                self.__setattr__(name, v)
            return v
        # Because __dict__ is overwrited by fields, so we need check mannaully invoke relation
        if name in self.__class__.__relations__:
            relation_property = self.__class__.__relations__[name]
            return relation_property.__get__(self)
        #
        raise AttributeError(f'\'{self.__class__.__name__}\' object has no attribute \'{name}\'')

    def __str__(self):
        return f'{self.__class__.__name__}{self.dict()}'

    @classmethod
    def get_type(cls, path):
        """ Get type of a path.

        :param path:
        """
        # Remove model name prefix, i.e, user.posts[0].title -> posts[0].title
        model_prefix = cls.__name__.lower() + '.'
        if path.startswith(model_prefix):
            key = path[len(model_prefix):]
        # Normalized the path, i.e, posts[0].title -> posts-0.title
        list_char = '-'
        path = path.replace('[', list_char).replace(']', '')
        #
        check_path = ''
        type_ = cls
        for key in path.split('.'):
            check_path += f'.{key}' if check_path else key
            if list_char in key:
                key_ = key.split(list_char)[0]
                if key_ not in type_.__fields__:
                    raise PathError(f'path {check_path} is invalid')
                type_ = get_args(type_.__fields__[key_].type)[0]
            else:
                if key not in type_.__fields__:
                    raise PathError(f'path {check_path} is invalid')
                type_ = type_.__fields__[key].type
        #
        return type_

    def copy(self, update: Dict[str, Any] = None, deep: bool = False):
        """ Copy logic. """
        update = update or {}
        v = dict(
            self._iter(),
            **update,
        )
        if deep:
            # chances of having empty dict here are quite low for using smart_deepcopy
            v = deepcopy(v)
        #
        cls = self.__class__
        m = cls.__new__(cls)
        object.__setattr__(m, '__dict__', v)
        fields_set = self.__fields_set__ | update.keys()
        object.__setattr__(m, '__fields_set__', fields_set)
        #
        return m

    def dict(
            self,
            encode: bool = False,
            include: dict = None,
            exclude: dict = None,
            include_relations: bool = False,
    ):
        """ Convert to dict.

        :param encode: Encode ObjectId/datetime to str
        :param include: Fields to include in the returned dictionary
        :param exclude: Fields to exclude from the returned dictionary
        :param include_relations: Include the relations of model
        """
        return dict(self._iter(to_dict=True, encode=encode,
                               include=include, exclude=exclude,
                               include_relations=include_relations))

    def _iter(
            self,
            to_dict: bool = False,
            encode: bool = False,
            include: dict = None,
            exclude: dict = None,
            include_relations: bool = False,
    ):
        """ Access model recrusively. """
        for field_name, field_value in self.__dict__.items():
            #
            yield field_name, self._get_value(field_value, to_dict,
                                              encode, include, exclude, include_relations)
        #
        if include_relations:
            for relation_name in self.__class__.__relations__:
                relation_value = getattr(self, relation_name)
                # Note: Prevent infinite recursion on calling relations
                yield relation_name, self._get_value(relation_value, to_dict,
                                                     encode, include, exclude, False)

    def _get_value(
            self, v,
            to_dict: bool,
            encode: bool,
            include: dict,
            exclude: dict,
            include_relations: bool,
    ):
        """ Access model field recrusively. """
        if isinstance(v, dict):
            return {
                k_: self._get_value(v_, to_dict, encode,
                                    include,
                                    exclude,
                                    include_relations)
                for k_, v_ in v.items()
            }
        elif isinstance(v, list):
            return [
                self._get_value(v_, to_dict, encode,
                                include,
                                exclude,
                                include_relations)
                for i, v_ in enumerate(v)
            ]
        elif isinstance(v, BaseModel):
            if to_dict:
                return v.dict(encode=encode, include=include, exclude=exclude, include_relations=include_relations)
            else:
                return v.copy()
        else:
            if encode:
                if isinstance(v, ObjectId):
                    return str(v)
                elif isinstance(v, datetime):
                    return v.strftime(DATETIME_FORMAT_SHORT)
            return v

    def json(self, **kwargs) -> str:
        """ Convert to json str. """
        return json.dumps(self.dict(), cls=ModelJSONEncoder, **kwargs)

    @classmethod
    def schema(cls):
        """ To json schema dict.

        NOTE:
        Return json schema is a subset of Object Schema from OAS 3.0.
        In order to keep all the things simple, we do not use complex keywords such as oneOf, $ref, patternProperties, additionalProperties, etc.
        https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#schemaObject
        https://swagger.io/docs/specification/data-models/

        However, we still have some grammars
          - add enum_titles to help code generation
          - add py_type to help code generation
          - add layout to help code generation
          - add type date
          - Add format to array, so that we can gen a component for the whole array
          - Add searchables to root object, so that it can be used to generate search form
          - Add sortables to root object, so that it can be used to generate order drowpdown
          - Add columns to root object, so that it can be used to generate columns for table
        """

        def _gen_schema(type_: Type):
            """ Generate schema for type. """
            if isinstance(type_, SimpleEnumMeta):
                enum = _gen_schema(type_.type)
                enum.update({
                    'enum': list(type_),
                    'enum_titles': type_.titles,
                    'format': Format.SELECT,
                })
                return enum
            elif issubclass(type_, BaseModel):
                properties = {}
                required = []
                for f_n, f_t in type_.__fields__.items():
                    field_schema = {}
                    origin = get_origin(f_t.type)
                    # Dict
                    if origin is dict:
                        # TODO: SUPPORT DICT
                        pass
                    # List
                    elif origin is list:
                        l_type = get_args(f_t.type)[0]
                        inner_type = _gen_schema(l_type)
                        field_schema.update({
                            'type': 'array',
                            'items': inner_type,
                            'py_type': f'List[{inner_type["py_type"]}]',
                        })
                    # built-in type, SimpleEnum or sub model
                    else:
                        field_schema.update(_gen_schema(f_t.type))
                    # default
                    if f_t.default:
                        # Skip if default is callable, e.g, datetime.now
                        if callable(f_t.default):
                            pass
                        else:
                            default = f_t.default
                            field_schema.update({'default': default})
                    # title
                    field_schema.update({'title': f_t.title if f_t.title else f_n.upper()})
                    # description
                    if f_t.description:
                        field_schema.update({'description': f_t.description})
                    # unit
                    if f_t.unit:
                        field_schema.update({'unit': f_t.unit})
                    # format, overwrite default format
                    if f_t.format:
                        field_schema.update({'format': f_t.format})
                        #
                        if f_t.format in [Format.DATE, Format.DATETIME]:
                            field_schema.update({'type': 'date'})
                    # required
                    properties[f_n] = field_schema
                    if f_t.required:
                        field_schema.update({'required': True})
                        required.append(f_n)
                #
                obj = {
                    'type': 'object',
                    'properties': properties,
                    'required': required,
                    'py_type': type_.__name__,
                }
                # layout
                layout = []
                if type_.__layout__:
                    rows = type_.__layout__.strip().splitlines()
                    for r in rows:
                        r = r.strip().strip(',')
                        if not r:
                            continue
                        layout.append([x.strip() for x in r.split(',')])
                else:
                    layout = properties.keys()
                #
                obj['layout'] = layout
                #
                return obj
            elif type_ is str:
                return {'type': 'string', 'format': Format.TEXT, 'py_type': 'str'}
            elif type_ is int:
                return {'type': 'integer', 'format': Format.INT, 'py_type': 'int'}
            elif type_ is float:
                return {'type': 'number', 'format': Format.FLOAT, 'py_type': 'float'}
            elif type_ is bool:
                return {'type': 'boolean', 'format': Format.CHECKBOX, 'py_type': 'bool'}
            elif type_ is ObjectId:
                return {'type': 'string', 'format': Format.OBJECTID, 'py_type': 'ObjectId'}
            elif type_ is datetime:
                return {'type': 'date', 'format': Format.DATETIME, 'py_type': 'datetime'}

        #
        ret = _gen_schema(cls)
        # Root level properties
        searchables = [('%s__%s' % s if isinstance(s, tuple) else s) for s in cls.__searchables__]
        if searchables:
            ret['searchables'] = searchables
        if cls.__sortables__:
            ret['sortables'] = cls.__sortables__
        #
        ret['columns'] = cls.__columns__ if cls.__columns__ else ret['required']
        #
        # print(json.dumps(ret))
        return ret
