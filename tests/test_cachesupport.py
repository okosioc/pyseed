# -*- coding: utf-8 -*-
"""
    test_cachesupport.py
    ~~~~~~~~~~~~~~

    Cache support testing cases.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2022/9/14
"""
import re
from datetime import datetime
from typing import List

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
    phone: str = None
    team: CTeam = RelationField(back_field_name='members', back_field_is_list=True, back_field_order=[('team_join_time', -1)])
    team_join_time: datetime = None
    update_time: datetime = None
    create_time: datetime = datetime.now


class CProject(CacheModel):
    """ Cache project defintion. """
    name: str
    members: List[CUser] = RelationField(required=False, back_field_name='projects', back_field_is_list=True, back_field_order=[('create_time', -1)])
    update_time: datetime = None
    create_time: datetime = datetime.now


def test_crud():
    """ Test cases for crud. """
    # Schema
    cuser_schema = CUser.schema()
    assert cuser_schema['relations'] == ['CTeam', 'CProject']
    assert cuser_schema['id_name'] == 'id'
    assert cuser_schema['id_type'] == 'int'
    cproject_schema = CProject.schema()
    assert cproject_schema['relations'] == ['CUser']

    # Init
    assert CUser.delete_many()
    assert CUser.count() == 0
    assert CTeam.delete_many()
    assert CTeam.count() == 0

    # C
    team1 = CTeam(name='team1')
    team1.save()
    user1 = CUser(name='user1', email='user1@dev', phone='13800138000', team=team1, team_join_time=datetime.now())
    user1.save()
    assert user1.id == 1

    # R
    assert CUser.find_one({'name': 'user1'}).email == user1.email
    assert len(CTeam.find()) == 1

    # Q
    assert len(CUser.find({'name': {'$regex': re.compile('^u')}})) == 1
    assert len(CUser.find({'phone': {'$regex': re.compile('^138')}})) == 1

    # U
    user2 = CUser(name='user3', email='user2@dev', team=team1, team_join_time=datetime.now())
    user2.save()
    user2.name = 'user2'
    user2.save()
    assert user2.id == 2
    assert len(team1.members) == 2

    # Q
    assert CUser.find_by_ids([1, 2])[1].name == user2.name

    # D
    assert user2.delete()
    assert CUser.find_one(2) is None
    assert len(CUser.find({'name': 'user2'})) == 0
    assert CUser.count() == 1

    # id calculation after deletion
    user3 = CUser({
        'name': 'user3',
        'email': 'user3@dev',
        'team': {
            'id': team1.id
        },
        'team_join_time': datetime.now(),
    })
    user3.save()
    assert user3.id == 2
    assert CUser.find_one(2).name == 'user3'

    # relation many to one
    del team1.members
    assert list(map(lambda x:x.id, team1.members)) == [user3.id, user1.id]  # sort DESCENDING

    # relation many-to-many
    project1 = CProject(name='project1', members=[user1, user2])
    project1.save()
    assert project1.members_ids == [user1.id, user2.id]
    project2 = CProject(name='project2', members=[user2])
    project2.save()
    assert len(user2.projects) == 2
