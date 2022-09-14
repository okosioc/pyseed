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
import sys
from abc import ABCMeta
from copy import deepcopy
from datetime import datetime
from typing import no_type_check, Dict, Type, Callable, get_origin, get_args, Set, Any, ForwardRef, List, Tuple

import inflection
from bson import ObjectId

from .error import SchemaError, DataError, PathError
from .utils import parse_layout, iterate_layout


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
    VIDEO = 'video'  # Video upload support
    IP = 'ip'
    OBJECTID = 'objectid'  # Default format for ObjectId
    CHECKBOX = 'checkbox'  # Default format for bool
    SWITCH = 'switch'
    HIDDEN = 'hidden'  # Hidden input
    LINK = 'link'  # Text input with an extenral link
    TIME = 'time'  # Time picker
    METRIC = 'metric'  # Statistic card for simple or object
    # Below values are used for inner model/dict or list of model/dict
    TAB = 'tab'  # Objects with tabs nav, i.e, [{}]
    TABLE = 'table'  # Objects in table, i.e, [{}]
    MODAL = 'modal'  # Objects with some fields in table and all fields in modal, i.e, [{}]
    GRID = 'grid'  # Objects in grid, i.e, [{}]
    TIMELINE = 'timeline'  # Objects in timeline, i.e, [{}]
    CALENDAR = 'calendar'  # Objects in calendar, i.e, [{}]
    MEDIA = 'media'  # Objects in media components like blog comments, tweets and the like, i.e, [{}]
    CHART = 'chart'  # Charting with series, i.e, {title, names, values}
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
# Field
#

class ModelField:
    """ Field definition. """
    __slots__ = (
        'name',
        'type',
        'default',
        'required',
        'readonly',
        'searchable',
        'sortable',
        'format',
        'icon',
        'title',
        'description',
        'unit',
        'source_field_name',
    )

    def __init__(self,
                 name: str = None, type_: Type = None,
                 default: Any = Undefined, required: bool = Undefined, readonly: bool = Undefined,
                 searchable: Comparator = Undefined, sortable: bool = Undefined,
                 format_: Format = None, icon: str = None, title: str = None, description: str = None, unit: str = None,
                 source_field_name: str = None):
        """ Init method.

        :param type_: annotaion for field, e.g, str or Dict[str, str] or List[Object]
        """
        self.name = name
        self.type = type_
        # default is none if undefined
        if default is Undefined:
            self.default = None
        else:
            self.default = default
        # required is true if undefined
        if required is Undefined:
            self.required = True
        else:
            self.required = required
        # readonly is false if undefined
        if readonly is Undefined:
            self.readonly = False
        else:
            self.readonly = readonly
        # searchable is none if undefined
        if searchable is Undefined:
            self.searchable = None
        else:
            self.searchable = searchable
        # sortable is false if undefined
        if sortable is Undefined:
            self.sortable = False
        else:
            self.sortable = sortable
        #
        self.format = format_
        self.icon = icon
        self.title = title
        self.description = description
        self.unit = unit
        #
        self.source_field_name = source_field_name

    def __str__(self):
        return f'{self.name}/{self.type}/{self.default}/{self.required}/{self.format}'


class RelationField(ModelField):
    """ Relation field definition. """

    __slots__ = ModelField.__slots__ + (
        'save_field_name',
        'save_field_order',
        'back_field_name',
        'back_field_is_list',
        'back_field_order',
        'back_field_format',
        'back_field_icon',
        'back_field_title',
        'back_field_description',
        'back_field_unit',
        'is_back_field',
    )

    def __init__(self,
                 name: str = None, type_: Type = None,
                 save_field_name: str = Undefined, save_field_order: List[Tuple[str, int]] = [],
                 back_field_name: str = None, back_field_is_list: bool = False, back_field_order: List[Tuple[str, int]] = [],
                 back_field_format: Format = None, back_field_icon: str = None, back_field_title: str = None,
                 back_field_description: str = None, back_field_unit: str = None, is_back_field: bool = False,
                 **kwargs):
        """ Init method.

        :param save_field_name: The name to use for saving current relation
        :param save_field_order: If the field is List, use this order when loading and saving
        :param back_field_name: The name to use for the relation from the related object back to this one
        :param back_field_is_list: If back field is list
        :param back_field_order: If back field is list, use this order when loading and saving
        :param is_back_field: If its a back field defined in related object
        """
        super().__init__(name, type_, **kwargs)
        # x12
        self.save_field_name = save_field_name
        self.save_field_order = save_field_order
        self.back_field_name = back_field_name
        self.back_field_is_list = back_field_is_list
        self.back_field_order = back_field_order
        self.back_field_format = back_field_format
        self.back_field_icon = back_field_icon
        self.back_field_title = back_field_title
        self.back_field_description = back_field_description
        self.back_field_unit = back_field_unit
        self.is_back_field = is_back_field


# ----------------------------------------------------------------------------------------------------------------------
# Relation
#

class relation(object):
    """ Decorator on a method to tell that it is used to fetch related models.

    class Post(BaseModel):
        creator_id: ObjectId
        tag_ids: List[ObjectId]

        @relation
        def creator(self):
            return User.find_one(self.creator_id)

        @relation
        def tags(self):
            return list(Tag.find({'_id':{'$in':self.tag_ids}})

    p = Post()
    p.creator
    p.tags

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

def evaluate_forward_ref(type_, globalns_):
    """ Create real class of forward ref. """
    if sys.version_info < (3, 9):
        return type_._evaluate(globalns_, None)
    else:
        return type_._evaluate(globalns_, None, set())


class ModelMeta(ABCMeta):
    """ Metaclass for model. """

    @no_type_check
    def __new__(mcs, name, bases, namespace, **kwargs):
        """ Create and return a new object.

        :param bases: Only contains current class' direct parents
        :param namespace: Only contains the fields of current object
        """
        fields: Dict[str, ModelField] = {}
        relations: Dict[str, relation] = {}
        properties: Dict[str, property] = {}
        # TODO: Support callable validators
        slots: Set[str] = namespace.get('__slots__', ())
        slots = {slots} if isinstance(slots, str) else set(slots)
        # Using for self-referencing, so we that we can remove all ForwardRef just after the class is created
        # If use ForwardRef('other_class_name'), we do not have appropriate timing to replace it to its real class
        # as we do not know if it is created or not
        has_forward_refs = False
        #
        for base in reversed(bases):
            if issubclass(base, BaseModel):  # True if base is BaseModel or its subclass
                # BaseModel do not have __fields__
                if base is not BaseModel:
                    fields.update(deepcopy(base.__fields__))
                # Id field's type should be defined in BaseModel/MongoModel, so we need to fetch them from bases
                if '__id_type__' not in namespace:
                    namespace['__id_type__'] = base.__id_type__
                    namespace['__id_name__'] = base.__id_name__

        def _validate_annotation(field_name, field_type):
            """ Validate field definition.

            Do not need to validate recrusively as referencing models has done their own validation.
            """
            nonlocal has_forward_refs
            # Validate if shadows a parent attribute
            for base_ in bases:
                if getattr(base_, field_name, None):
                    raise SchemaError(f'{field_name}: {field_type} shadows a parent attribute')
            #
            # Validate annotation, i.e, List[str], origin is List while str is check_type
            #
            origin = get_origin(field_type)
            # Simple, including built-in type, SimpleEnum or sub model
            if origin is None:
                check_type = field_type
            # Dict
            elif origin is dict:
                k_type, v_type = get_args(field_type)
                if k_type is not str:
                    raise SchemaError(f'{field_name}: {field_type} only support str keys')
                #
                check_type = v_type
            # List
            elif origin is list:
                check_type = get_args(field_type)[0]
            else:
                raise SchemaError(f'{field_name}: {field_type} is not supported')
            #
            # Check if inner type is valid
            #
            if isinstance(check_type, ForwardRef):
                has_forward_refs = True
            elif isinstance(check_type, SimpleEnumMeta):
                enum_types = set()
                for member in check_type:
                    enum_types.add(type(member))
                    if type(member) not in AUTHORIZED_TYPES:
                        raise SchemaError(f'{field_name}: {check_type} is not an authorized type')
                if len(enum_types) == 0:
                    raise SchemaError(f'{field_name}: {check_type} has not defined any enum values')
                if len(enum_types) > 1:
                    raise SchemaError(f'{field_name}: {check_type} can not have more than one type')
            elif issubclass(check_type, BaseModel):
                pass
            elif check_type not in AUTHORIZED_TYPES:
                raise SchemaError(f'{field_name}: {check_type} is not an authorized type')
            #
            return check_type, origin

        # Validation
        skips = set()
        if namespace.get('__qualname__') != 'BaseModel':
            #
            # Iterate each annotation(field)
            # Similar to typing.get_type_hints, https://docs.python.org/3/library/typing.html
            # But we can not use get_type_hints() here as it tries to create class from ForwardRef
            #
            annotations = namespace.get('__annotations__', {})
            for ann_name, ann_type in annotations.items():
                # Skip
                if ann_name.startswith('__'):
                    skips.add(ann_name)
                    continue
                # Validate
                _, f_origin = _validate_annotation(ann_name, ann_type)
                # Create another field for RelationField
                save_field = None
                #
                value = namespace.get(ann_name, Undefined)
                # Field is required if undefined
                if value is Undefined:
                    field = ModelField(name=ann_name, type_=ann_type, default=None, required=True)
                # Field is NOT required
                elif value is None:
                    field = ModelField(name=ann_name, type_=ann_type, default=None, required=False)
                # Define a RelationField
                elif isinstance(value, RelationField):
                    field = value
                    field.name = ann_name
                    field.type = ann_type
                    # When save_field is underfined in this object, it will go to its default setting logic
                    if field.save_field_name is Undefined:
                        if f_origin is list:
                            field.save_field_name = ann_name + '_ids'
                        else:
                            field.save_field_name = ann_name + '_id'
                    # Create the save field
                    # Please note: if it is none means it is the auto-created back relation in related object
                    id_type = namespace.get('__id_type__')
                    save_field = ModelField(
                        name=field.save_field_name, type_=List[id_type] if f_origin is list else id_type,
                        required=field.required,
                        source_field_name=ann_name,  # Mark the source field
                    )
                    # Set required to false
                    field.required = False
                    # back_field should always has a meaningful value
                    # if it is none, this field's object name is used, e.g, user.team -> team.users
                    if field.back_field_name is None:
                        field.back_field_name = name.lower()
                        if field.back_field_is_list:
                            field.back_field_name = inflection.pluralize(field.back_field_name)
                # Define a ModelField
                elif isinstance(value, ModelField):
                    # Supplement field's name and type, as we use annotation to define a model field
                    # e.g, name: str = Field(title='User Name'), so need to mannaully set name/str here
                    field = value
                    field.name = ann_name
                    field.type = ann_type
                # Set default value
                else:
                    field = ModelField(name=ann_name, type_=ann_type, default=value, required=True)
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
                if save_field is not None:
                    fields[save_field.name] = save_field
            #
            # Relations & Properties
            #
            for attr in namespace:
                if isinstance(namespace.get(attr), relation):
                    relations[attr] = namespace.get(attr)
                if isinstance(namespace.get(attr), property):
                    properties[attr] = namespace.get(attr)
        #
        # Check depth
        #
        max_list_depth = 0

        def _iter(field_name, field_type, level):
            """ Check all the fields recrusively. """
            nonlocal max_list_depth
            max_list_depth = max(max_list_depth, level)
            #
            origin_ = get_origin(field_type)
            is_in_list = False
            if origin_ is dict:
                _, check_type = get_args(field_type)
            elif origin_ is list:
                check_type = get_args(field_type)[0]
                is_in_list = True
            else:
                check_type = field_type
            #
            if isinstance(check_type, ForwardRef):  # Skip forwardref, always using for self-referencing
                pass
            elif isinstance(check_type, SimpleEnumMeta):
                pass
            elif issubclass(check_type, BaseModel):
                #
                for a_n, a_t in check_type.__dict__.get('__annotations__', {}).items():
                    _iter(a_n, a_t, level + (1 if is_in_list else 0))

        #
        for f in fields.values():
            _iter(f.name, f.type, 0)
        #
        if max_list_depth >= 3:
            raise SchemaError(f'Model {name} is too deep: {max_list_depth}')
        #
        # Create class
        #
        exclude_from_namespace = fields.keys() | skips | relations.keys() | properties.keys() | {'__slots__'}
        new_namespace = {
            '__fields__': fields,
            '__slots__': slots,
            '__relations__': relations,
            '__properties__': properties,
            **{n: v for n, v in namespace.items() if n not in exclude_from_namespace},
        }
        cls = super().__new__(mcs, name, bases, new_namespace, **kwargs)
        #
        # Try to update ForwardRef after class is created
        #
        if has_forward_refs:
            globalns = sys.modules[cls.__module__].__dict__.copy()
            globalns.setdefault(cls.__name__, cls)
            for f in cls.__fields__.values():
                f_origin = get_origin(f.type)
                if f_origin is dict:
                    _, f_type = get_args(f.type)
                    if f_type.__class__ == ForwardRef:
                        f.type = Dict[evaluate_forward_ref(f_type, globalns)]
                elif f_origin is list:
                    f_type = get_args(f.type)[0]
                    if f_type.__class__ == ForwardRef:
                        f.type = List[evaluate_forward_ref(f_type, globalns)]
                else:
                    f_type = f.type
                    if f_type.__class__ == ForwardRef:
                        f.type = evaluate_forward_ref(f_type, globalns)
        #
        # Try to create back field of relation fields after this class is created
        #
        for f in cls.__fields__.values():
            if isinstance(f, RelationField):
                back_field = RelationField(
                    name=f.back_field_name, type_=List[cls] if f.back_field_is_list else cls,
                    save_field_name=f.save_field_name, save_field_order=f.back_field_order,
                    required=False, readonly=True,  # Relation field is lazy loaded, so it is not required
                    format_=f.back_field_format, icon=f.back_field_icon, title=f.back_field_title, description=f.back_field_description,
                    unit=f.back_field_unit,
                    is_back_field=True,  # Mark this field to be a back field created by a relation field
                )
                f_origin = get_origin(f.type)
                if f_origin is dict:
                    _, f_type = get_args(f.type)
                elif f_origin is list:
                    f_type = get_args(f.type)[0]
                else:
                    f_type = f.type
                # Update related model
                f_type.__fields__[f.back_field_name] = back_field
                f_type.__slots__ = tuple(f_type.__slots__) + (f.back_field_name,)

        #
        return cls


class BaseModel(metaclass=ModelMeta):
    """ Base Model. """

    __slots__ = ('__dict__', '__errors__')
    __doc__ = ''
    #
    # Fields may be overwrited
    #
    # The id field name
    __id_name__ = '_id'
    __id_type__ = ObjectId
    #
    __icon__ = None
    __title__ = None
    __description__ = None
    # TODO: Validate all fields in layout are defined
    # Define fields can be show in query result table or card
    __columns__ = []
    # Define field groups, which can be included by index in layouts
    # e.g,
    # __groups__ = [
    #   '''
    #   name, status
    #   phone
    #   ''',
    #   '''
    #   password
    #   ''',
    # ]
    # __read__ = '''
    #   $, (0, 1)
    # '''
    __groups__ = []
    # Define layouts to render read or form page
    __layout__ = None
    __read__ = None
    __form__ = None

    def __init__(self, *d: Dict[str, Any], **data: Any) -> None:
        """ Init.

        :param d: create model from dict
        :param **data: create model from kwargs
        """
        data_ = d[0] if d else data
        values, errors = self.validate_data(data_)
        object.__setattr__(self, '__dict__', values)
        object.__setattr__(self, '__errors__', errors)

    def validate(self):
        """ Validate self. """
        _, errors = self.validate_data(self.__dict__)
        object.__setattr__(self, '__errors__', errors)
        return errors

    @classmethod
    def validate_data(cls, data: Dict[str, Any]):
        """ Validate data against model.

        :param data: Inner sub models can be dict or model instance
        """
        values = {}
        errors = []
        # Validate against schema
        # print(f'Validate {cls.__name__} with {data}')
        for field_name, field_type in cls.__fields__.items():
            # Skip relation field's validation
            if isinstance(field_type, RelationField):
                continue
            #
            # Update id/ids field created by relation field
            # But can not do update in back relation field
            # e.g,
            # user.team -> team.members, team_id is saved in user model, we can use user.team = another team to update it
            # However, it is not supported to update by team.members.append(user), because it is complex to implement this:
            #   Remember which users are removed and appended from team
            #   Add transaction support to update these users before updating team object
            #
            if field_type.source_field_name is not None:  # e.g, team_id is created by team relation, so source field name of team_id is team
                source_field = cls.__fields__[field_type.source_field_name]
                relation_value = data.get(source_field.name, Undefined)  # get team value
                # RelationField's value is lazy loaded, undefined means it is not load, so trust the value in current field
                if relation_value is Undefined:
                    pass
                # If it is not Undefined, means it is already loaded and may be updated programmtically, so overwrite current field
                else:
                    update_value = None
                    if isinstance(relation_value, list):
                        update_value = []
                        for v in relation_value:
                            if isinstance(v, dict):  # Value can be raw dict against related model
                                id_ = v.get(cls.__id_name__)
                            else:  # Value should be instance of relatited model
                                id_ = getattr(v, cls.__id_name__)
                            #
                            if id_:
                                if not isinstance(id_, cls.__id_type__):
                                    id_ = cls.__id_type__(id_)
                                #
                                update_value.append(id_)
                    else:
                        if isinstance(relation_value, dict):
                            id_ = relation_value.get(cls.__id_name__)
                        else:
                            id_ = getattr(relation_value, cls.__id_name__)
                        #
                        if id_:
                            if not isinstance(id_, cls.__id_type__):
                                id_ = cls.__id_type__(id_)
                            #
                            update_value = id_
                    # update_value can be none or [], meaning clear the field
                    data[field_name] = update_value
            #
            field_value, field_errors = cls._validate_field(field_type, data.get(field_name, Undefined))
            if field_value is not Undefined:
                values[field_name] = field_value
            if field_errors:
                errors.extend(field_errors)
        # Check if any non-defined fields
        undefined_fields = set(data.keys()) - set(cls.__fields__.keys())
        if len(undefined_fields) > 0:
            # Do not raise error for non-defined fields
            # errors.append(f'{cls.__name__}: Found undefined data fields, {undefined_fields}')
            pass
        #
        return values, errors

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
                # Value can be raw dict against sub model
                if isinstance(type_value, dict):
                    type_value = type_(**value)
                    if type_value.__errors__:
                        type_errors.extend(type_value.__errors__)
                # Value should be same type
                elif not isinstance(type_value, type_):
                    type_errors.append(
                        DataError(f'{cls.__name__}.{field.name}: {field.type} only support {type_} value'))
                # Value is a sub model
                else:
                    errors = type_value.validate()
                    if errors:
                        type_errors.extend(errors)
            elif not isinstance(type_value, type_):
                type_errors.append(DataError(f'{cls.__name__}.{field.name}: {field.type} only support {type_} value'))
        #
        return type_value, type_errors

    def __setattr__(self, name, value):
        """ Set a field. """
        self.__dict__[name] = value

    def __delattr__(self, name):
        """ Del a field. """
        if name not in self.__dict__:
            raise AttributeError(name)
        #
        del self.__dict__[name]

    def __getattr__(self, name):
        """ Try to init a field if it is not in self.__dict__.

        Note: When an attribute is accessed, __getattribute__ is invoked firstly
        and then if the attribute wasn't found, __getattr__ should be invoked.
        """
        if name in self.__class__.__fields__:
            field = self.__class__.__fields__[name]
            f_type = field.type
            f_origin = get_origin(f_type)
            # Try to init relation values lazy
            if isinstance(field, RelationField):
                # TODO: filter param is in mongodb's format, maybe more abstract approach is needed
                if f_origin is None:
                    # This is a back field created by relation field, means id is saved in one relation object
                    if field.is_back_field:
                        default = f_type.find_one({field.save_field_name: self.__dict__.get(f_type.__id_name__)})
                    else:
                        default = f_type.find_one({f_type.__id_name__: self.__dict__.get(field.save_field_name)})
                elif f_origin is list:
                    l_type = get_args(f_type)[0]
                    # This is a back field created by relation field, means this object id is saved in many relation objects
                    if field.is_back_field:
                        # Typical many-to-one definition way, i.e, using a foreign key to store related object's id
                        # In such case, may return very big amount of object so we only fetch part of it, i.e, 100 records
                        # e.g,
                        # Relation field is defined in User using field name team, so the team id stores in a field name team_id
                        # Below back relation field auto-created in Team
                        #   members: List[User] -> User.find({team_id, self._id}, sort=[{team.join_time, 1}])
                        default = list(
                            l_type.find(
                                {field.save_field_name: self.__dict__.get(l_type.__id_name__)},
                                sort=field.save_field_order,
                                limit=100)
                        )
                    else:
                        # Please note: Databases like mongodb supports list format field
                        # In such case, the ids field should not be very large, so we fetch all the objects and sort them by id's position
                        # e.g,
                        # Relation field is defined in Team using field name members, so the team ids store in a field name members_ids
                        #   members: List[User] -> User.find({_id: {$in: self.members_ids}})
                        ids = self.__dict__.get(field.save_field_name)
                        if ids is None:
                            default = []
                        else:
                            default = list(l_type.find({l_type.__id_name__: {'$in': ids}}))
                            default.sort(key=lambda i: ids.index(getattr(i, l_type.__id_name__)))
                elif f_origin is dict:
                    default = None
                # If relation return None, we need to set the field to None
                # So that in the second access on the field, we can return None directly
                # This is a key step to implement the lazy loading for relation field
                self.__setattr__(name, default)
            else:
                default = None
                if f_origin is None:
                    if issubclass(f_type, BaseModel):
                        # Create inner model automatically
                        default = f_type()
                elif f_origin is list:
                    default = []
                elif f_origin is dict:
                    default = {}
                #
                if default is not None:
                    self.__setattr__(name, default)
            #
            return default
        # Because __dict__ is overwrited by values, so we need invoke relation mannaully
        if name in self.__class__.__relations__:
            rel = self.__class__.__relations__[name]
            return rel.__get__(self)
        # Invoke property mannaully
        if name in self.__class__.__properties__:
            prp = self.__class__.__properties__[name]
            return prp.__get__(self)
        #
        raise AttributeError(f'\'{self.__class__.__name__}\' object has no attribute \'{name}\'')

    def __str__(self):
        return f'{self.__class__.__name__}{self.dict()}'

    def __repr__(self):
        return f'{self.dict()}'

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
            field = self.__class__.__fields__[field_name]
            if isinstance(field, RelationField):
                if include_relations:
                    yield field_name, getattr(self, field_name)
            else:
                yield field_name, self._get_value(field_value, to_dict, encode, include, exclude, include_relations)

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
                k_: self._get_value(v_, to_dict, encode, include, exclude, include_relations)
                for k_, v_ in v.items()
            }
        elif isinstance(v, list):
            return [
                self._get_value(v_, to_dict, encode, include, exclude, include_relations)
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
            #
            return v

    def json(self, **kwargs) -> str:
        """ Convert to json str. """
        return json.dumps(self.dict(), cls=ModelJSONEncoder, **kwargs)

    @classmethod
    def find_one(cls, filter_or_id, *args, **kwargs):
        """ abstract method, use it to fetch one related model. """
        raise NotImplementedError()

    @classmethod
    def find(cls, *args, **kwargs):
        """ abstract method, use it to fetch many related models. """
        raise NotImplementedError()

    @classmethod
    def schema(cls):
        """ To json schema dict.

        NOTE:
        Return json schema is a subset of Object Schema from OAS 3.0.
        In order to keep all the things simple, we do not use complex keywords such as oneOf, $ref, patternProperties, additionalProperties, etc.
        https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#schemaObject
        https://swagger.io/docs/specification/data-models/

        However, we still have some grammars
          - add type date
          - add enum_titles, py_type, layout, form, read, icon, readonly to help code generation
          - Add format to array, so that we can gen a component for the whole array
          - Add searchables to object, so that it can be used to generate search form
          - Add sortables to object, so that it can be used to generate order drowpdown
          - Add columns to object, so that it can be used to generate columns for table
        """

        def _gen_schema(type_: Type, parents=[]):
            """ Generate schema for type. """
            if isinstance(type_, SimpleEnumMeta):
                enum = _gen_schema(type_.type, parents)
                enum.update({
                    'enum': list(type_),
                    'enum_titles': type_.titles,
                    'format': Format.SELECT,
                    'py_type': type_.__name__,
                })
                return enum
            elif issubclass(type_, BaseModel):
                # Need to prevent recursively access
                # e.g,
                #   User.friends:User == #User
                #   User.team:Team -> Team.members:List[User] == List[#User]
                check_parents = [type_.__name__] + parents
                #
                properties = {}
                required, searchables, sortables, relations = [], [], [], []
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
                        if l_type.__name__ in check_parents:
                            field_schema.update({
                                'type': 'array',
                                # https://json-schema.org/understanding-json-schema/structuring.html#recursion
                                # Your program should replace the {$ref:} with reference object's schema
                                'items': {'$ref': f'#{l_type.__name__}'},
                                'py_type': f'List[{type_.__name__}]',
                            })
                        else:
                            inner_type = _gen_schema(l_type, check_parents)
                            field_schema.update({
                                'type': 'array',
                                'items': inner_type,
                                'py_type': f'List[{inner_type["py_type"]}]',
                            })
                    # built-in type, SimpleEnum or sub model
                    else:
                        if f_t.type.__name__ in check_parents:
                            field_schema.update({
                                'type': 'object',
                                # Your program should replace the {$ref:} with properties of reference object's schema only
                                # But should NOT overwrite the icon/title/description/... as these fields may use different values
                                '$ref': f'#{f_t.type.__name__}',
                                'py_type': f_t.type.__name__,
                            })
                        else:
                            inner_type = _gen_schema(f_t.type, check_parents)
                            field_schema.update(inner_type)
                    # default
                    if f_t.default:
                        # Skip if default is callable, e.g, datetime.now
                        if callable(f_t.default):
                            pass
                        else:
                            default = f_t.default
                            field_schema.update({'default': default})
                    # icon
                    if f_t.icon:
                        field_schema.update({'icon': f_t.icon})
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
                    if f_t.required:
                        field_schema.update({'required': True})
                        required.append(f_n)
                    # readonly
                    if f_t.readonly:
                        field_schema.update({'readonly': True})
                    # searchable
                    if f_t.searchable is not None:
                        searchables.append((f_n, f_t.searchable))
                    # sortable
                    if f_t.sortable is True:
                        sortables.append(f_n)
                    # relation
                    if isinstance(f_t, RelationField):
                        field_schema.update({'is_relation': True})
                        relations.append(f_n)
                    #
                    properties[f_n] = field_schema
                #
                obj = {
                    'type': 'object',
                    'properties': properties,
                    'required': required,
                    'columns': type_.__columns__ if type_.__columns__ else required,  # Using required fields as columns as the default
                    'py_type': type_.__name__,
                    'icon': type_.__icon__ if type_.__icon__ else None,
                    'title': type_.__title__ if type_.__title__ else type_.__name__.upper(),
                    'description': type_.__description__ if type_.__description__ else None,
                }
                # layout, if not defined, each field has one row
                layout = parse_layout(type_.__layout__ if type_.__layout__ else '\n'.join(properties.keys()))[0]
                obj['layout'] = layout
                obj['read'] = parse_layout(type_.__read__)[0] if type_.__read__ else layout
                obj['form'] = parse_layout(type_.__form__)[0] if type_.__form__ else layout
                obj['groups'] = [parse_layout(g)[0] for g in type_.__groups__]
                # each column in layout can be blank('')/summary($)/hyphen(-)/group(number)/field(string) suffixed with query and span string
                # read_fields/form_fields just return field names
                obj['read_fields'] = list(iterate_layout(obj['read'], obj['groups']))
                obj['form_fields'] = list(iterate_layout(obj['form'], obj['groups']))
                # searchables
                obj['searchables'] = [('{}__{}'.format(*s) if s[1] != Comparator.EQ else s[0]) for s in searchables]
                # sortables
                obj['sortables'] = sortables
                # relations
                obj['relations'] = relations
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
        # print(json.dumps(ret))
        return ret
