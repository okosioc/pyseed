# -*- coding: utf-8 -*-
"""
    test_mongosupport
    ~~~~~~~~~~~~~~

    Mongo support test cases.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/8/11
"""

import pytest

from pymongo.errors import DuplicateKeyError
from py3seed import DataError

from .core.models import User, Team


def test_crud(db):
    """ Test cases for crud. """
    # Init
    assert User.delete_many({})
    assert User.count({}) == 0
    assert Team.delete_many({})
    assert Team.count({}) == 0
    # C
    team = Team(name='test')
    team.save()
    #
    usr = User(team=team)
    usr.name = 'test'
    usr.email = 'test'
    usr.save()
    assert User.count({}) == 1
    # R
    assert User.find_one({'name': 'test'}).name == 'test'
    # id property
    assert usr.id == usr._id

    # U
    del usr.name
    # Validation
    with pytest.raises(DataError, match='name') as excinfo:
        usr.save()
    # print(excinfo.value)

    usr.name = 'test'
    # DulplicateKey from pymongo
    with pytest.raises(DuplicateKeyError) as excinfo:
        usr.save(insert_with_id=True)
    # print(excinfo.value)

    usr.save()
    assert User.find_one({'name': 'test'}).name == 'test'

    # Relation read
    assert usr.team._id == team._id
    assert len(team.members) == 1
    assert team.members[0]._id == usr._id

    # relation update
    team1 = Team(name='test1')
    team1.save()
    usr.team = team1
    usr.save()
    assert usr.team._id == team1._id

    # back relation
    usr1 = User(name='test1', email='test1', team=team1)
    usr1.save()
    assert len(team1.members) == 2
    usr2 = User(name='test2', email='test2', team=team1)
    usr2.save()
    # reset back relations
    del team1.members
    assert len(team1.members) == 3

    # dict
    user_dict = {
        'name': 'test3',
        'email': 'test3',
        'team': {'_id': team1._id}
    }
    usr3 = User(user_dict)
    usr3.save()
    # reset back relations
    del team1.members
    assert len(team1.members) == 4

    # D
    assert usr.delete()
    # Verify
    assert User.count({}) == 3
