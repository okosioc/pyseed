# -*- coding: utf-8 -*-
"""
    test_cachesupport.py
    ~~~~~~~~~~~~~~

    Cache support testing cases.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2022/9/14
"""
from datetime import datetime

from py3seed import CacheModel, RelationField


class CTeam(CacheModel):
    """ Cache team definition"""
    name: str
    update_time: datetime = None
    create_time: datetime = datetime.now


class CUser(CacheModel):
    """ Cache user definition. """
    name: str
    email: str
    team: CTeam = RelationField(back_field_name='members', back_field_is_list=True, back_field_order=[('team_join_time', 1)])
    update_time: datetime = None
    create_time: datetime = datetime.now


def test_crud():
    """ Test cases for crud. """
    # Init
    assert CUser.delete_many()
    assert CUser.count() == 0
    assert CTeam.delete_many()
    assert CTeam.count() == 0

    # C
    team1 = CTeam(name='team1')
    team1.save()
    user1 = CUser(name='user1', email='user1@dev', team=team1)
    user1.save()
    assert user1.id == 1

    # R
    assert CUser.find_one({'name': 'user1'}).email == user1.email
    assert len(CTeam.find()) == 1

    # U
    user2 = CUser(name='user3', email='user2@dev', team=team1)
    user2.save()
    user2.name = 'user2'
    user2.save()
    assert len(team1.members) == 2

    # D
    assert user2.delete()
    assert CUser.count() == 1
