# -*- coding: utf-8 -*-
"""
    test_websupport
    ~~~~~~~~~~~~~~

    websupoort test cases.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2023/12/7
"""

from bson import ObjectId
from datetime import datetime
from werkzeug.datastructures import MultiDict

from py3seed import populate_model, populate_search
from .core.models import UserStatus, UserRole, User


def test_populate_model(db):
    """ Test cases for populate_model. """
    now = datetime.now()
    oid = ObjectId()
    # Use a mulitdict to simulate a form data, please note all keys starts with user. and all values are string type
    md = MultiDict(
        [
            ('user.name', 'test'),
            ('user.point', '2'),
            ('user.status', 'rejected'),
            ('user.roles[0]', '9'),
            ('user.roles[1]', '2'),
            ('user.team_id', str(oid)),
            ('user.team_join_time', now.strftime('%Y-%m-%d %H:%M:%S')),
        ]
    )
    user = populate_model(md, User)
    assert user.name == 'test'
    assert user.status == UserStatus.REJECTED  # Convert to simple enum
    assert user.roles == [UserRole.ADMIN, UserRole.EDITOR]  # Convert to list of simple enum with int type
    assert user.point == 2  # Convert to int
    assert user.team_id == oid  # Convert to ObjectId
    assert user.team_join_time.strftime('%Y-%m-%d') == now.strftime('%Y-%m-%d')  # Convert to datetime


def test_populate_search():
    """ Test cases for populate_search. """
    # Use a mulitdict to simulate a form data, please note all keys start with search. and all values are string type
    md = MultiDict(
        [
            ('search.name', ''),
            ('search.name__like', 'test'),
            ('search.point__gt', '0'),
            ('search.point__lt', '100'),
            ('search.status__in', 'normal'),
            ('search.roles', '2'),
            ('search.roles', '9'),
        ]
    )
    search, condition = populate_search(md, User)
    # test search
    assert 'name' not in search
    assert search['name__like'] == 'test'
    assert search['roles'] == ['2', '9']
    # test conditiopn
    assert condition['name']['$regex'].match('this is a test')  # Like comparator
    assert {'status': condition['status']} == {'status': {'$in': [UserStatus.NORMAL]}}
    assert {'roles': condition['roles']} == {'roles': {'$in': [UserRole.EDITOR, UserRole.ADMIN]}}  # Equal comparator on list field
    assert {'point': condition['point']} == {'point': {'$gt': 0, '$lt': 100}}  # Convert to int
