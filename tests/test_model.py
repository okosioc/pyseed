# -*- coding: utf-8 -*-
"""
    test_model
    ~~~~~~~~~~~~~~

    Model test cases.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/8/10
"""

import json
from datetime import datetime
from typing import List, Dict, ForwardRef

import pytest

from py3seed import SimpleEnum, DATETIME_FORMAT, MongoModel, BaseModel, ModelField, Comparator


class UserRole(SimpleEnum):
    """ User role. """
    MEMBER = 1
    EDITOR = 2
    ADMIN = 9


class UserStatus(SimpleEnum):
    """ User Status. """
    NORMAL = 'normal'
    REJECTED = 'rejected'


class LastLogin(BaseModel):
    """ last login modal. """
    ip: str
    time: datetime


class Comment(BaseModel):
    """ Comment model. """
    author: str
    content: str
    date: datetime = datetime.now


class Post(BaseModel):
    """ Post model. """
    title: str
    content: str
    date: datetime = datetime.now
    likes: int = 0
    comments: List[Comment] = None


class User(MongoModel):
    """ User definition. """
    name: str = ModelField(searchable=Comparator.LIKE)
    email: str
    password: str = None
    intro: str = None
    avatar: str = None
    point: int = ModelField(readonly=True, default=0)
    status: UserStatus = ModelField(default=UserStatus.NORMAL, searchable=Comparator.EQ)
    roles: List[UserRole] = [UserRole.MEMBER]

    sibling: ForwardRef('User') = None  # Self-referenced by string
    siblings: List[ForwardRef('User')] = None

    update_time: datetime = None
    create_time: datetime = datetime.now

    last_login: LastLogin = None

    posts: List[Post] = None

    l: List[str] = None
    d: Dict[str, str] = None

    __columns__ = ['avatar', 'name', 'email', 'status', 'create_time']
    __layout__ = '''
    avatar
    name, email
    password,
    point#4, (status, roles)#8
    -
    $#4, (last_login?is_x=true#6, posts#6)?is_y=true#8
    '''
    __indexes__ = [{'fields': ['email'], 'unique': True}]


def test_model():
    """ Test cases for modal definition. """
    # Test schema
    schema = User.schema()
    assert schema['type'] == 'object'
    assert schema['properties']['_id']['py_type'] == 'ObjectId'
    assert schema['properties']['point']['readonly']
    assert schema['properties']['status']['enum'] == list(UserStatus)
    assert schema['properties']['sibling']['$ref'] == '#'
    assert schema['properties']['siblings']['type'] == 'array'
    assert schema['properties']['siblings']['items']['$ref'] == '#'
    assert schema['properties']['posts']['items']['properties']['title']['type'] == 'string'
    assert schema['properties']['posts']['items']['properties']['comments']['items']['properties']['date'][
               'type'] == 'date'
    assert len(schema['columns']) == len(User.__columns__)
    assert len(schema['layout']) == 6
    assert schema['layout'][0][0]['name'] == 'avatar'  # row 0, column 0
    assert schema['layout'][3][1]['name'] == 'status+roles'  # row 3, column 1
    assert schema['layout'][3][1]['name_snake'] == 'status_roles'
    assert schema['layout'][3][1]['span'] == 8
    assert schema['layout'][3][1]['children'][0]['name'] == 'status'  # row 2, column 1, children 0
    assert schema['layout'][5][0]['name'] == '$'  # row 4, column 0
    assert schema['layout'][5][0]['span'] == 4
    assert schema['layout'][5][1]['name'] == 'last_login+posts'  # row 4, column 1
    assert schema['layout'][5][1]['name_kebab'] == 'last-login-posts'
    assert schema['layout'][5][1]['span'] == 8
    assert schema['layout'][5][1]['children'][0]['params']['is_x']  # row 2, column 1, children 0
    assert schema['layout'][5][1]['children'][1]['name'] == 'posts'  # row 2, column 1, children 1
    assert schema['layout'][5][1]['children'][1]['span'] == 6
    assert schema['searchables'] == ['name__like', 'status']

    # Prepare an instance of User
    now = datetime.now()
    usr = User()

    # Test default values
    assert usr.point == 0
    assert usr.status == UserStatus.NORMAL
    assert usr.roles[0] == UserRole.MEMBER
    assert len(usr.l) == 0

    # Test referencing modal
    usr.last_login.ip = '127.0.0.1'
    usr.last_login.time = now
    assert usr.last_login.ip == '127.0.0.1'

    # Test self-referencing
    usr.sibling = User(name='sibling', email='sibling')
    usr.siblings = [
        User(name='sibling-0', email='sibling-0'),
        User(name='sibling-1', email='sibling-1'),
    ]
    assert type(usr.sibling) == User
    assert type(usr.siblings[0]) == User
    assert len(usr.siblings) == 2

    # Test copy
    another_usr = usr.copy()
    assert usr.point == another_usr.point
    assert usr != another_usr
    assert usr.last_login.ip == another_usr.last_login.ip
    assert usr.last_login != another_usr.last_login

    # Test json
    json_ = json.loads(usr.json())
    assert json_['create_time'] == usr.create_time.strftime(DATETIME_FORMAT)

    # Test dict
    admin = User(
        name='admin',
        email='admin',
        roles=[UserRole.ADMIN],
        last_login=LastLogin(ip='127.0.0.1', time=now),
        posts=[Post(title='admin', content='content')]
    )
    editor = User(**{
        'name': 'editor',
        'email': 'editor',
        'last_login': {'ip': '127.0.0.1', 'time': now},
        'posts': [{'title': 'editor', 'content': 'editor'}]
    })
    assert len(admin.posts) == len(editor.posts)

    # Test validate
    def _validate_and_check_message(message):
        errors = usr.validate()
        assert next((e for e in errors if message in e.message), None) is not None

    _validate_and_check_message('User.name')
    usr.name = 'test'
    usr.email = 'test'

    # Test deleting field
    del usr.name
    with pytest.raises(AttributeError):
        del usr.name
    # Validate after deleting
    _validate_and_check_message('User.name')
    usr.name = 'test'

    usr.posts.append(Post())
    _validate_and_check_message('Post.title')
    pst = usr.posts[0]
    pst.title = 'test'
    pst.content = 'test'

    usr.status = 'DELETED'
    _validate_and_check_message('User.status')
    usr.status = UserStatus.NORMAL

    pst.comments.append(Comment(author='test', content='test'))

    # Should be valid
    # print(usr.validate())
    assert len(usr.validate()) == 0
