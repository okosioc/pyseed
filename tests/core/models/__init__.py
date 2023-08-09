# -*- coding: utf-8 -*-
"""
    __init__.py
    ~~~~~~~~~~~~~~

    # Enter description here

    :copyright: (c) 2021 by weiminfeng.
    :date: 2023/7/5
"""

from datetime import datetime
from typing import List, Dict, ForwardRef

from py3seed import SimpleEnum, DATETIME_FORMAT, MongoModel, BaseModel, ModelField, Comparator, RelationField, Format


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


class Team(MongoModel):
    """ Team definition. """
    name: str = ModelField(searchable=Comparator.LIKE)
    phone: str = None
    logo: str = ModelField(required=False, format_=Format.IMAGE)
    remarks: str = ModelField(required=False, format_=Format.TEXTAREA)
    managers: List[str] = None
    #
    update_time: datetime = None
    create_time: datetime = datetime.now
    #
    __icon__ = 'users'
    __views__ = {
        'www://team-members': '''#!read?title=Members
            1#summary4,    members#8                                                  
              logo           avatar, name, status, roles, email, phone, team_join_time
              name
              phone                                                              
              members                                                                 
              create_time
        ''',
    }


def evens():
    """ return evens for depends testing. """
    return [0, 2, 4, 6, 8]


class User(MongoModel):
    """ User definition. """
    name: str = ModelField(searchable=Comparator.LIKE)
    email: str
    password: str = None
    phone: str = None
    intro: str = None
    avatar: str = None
    point: int = ModelField(editable=False, default=0)
    status: UserStatus = ModelField(default=UserStatus.NORMAL, searchable=Comparator.EQ)
    roles: List[UserRole] = [UserRole.MEMBER]

    odd: int = ModelField(required=False, format_=Format.SELECT, depends=[1, 3, 5, 7, 9])
    even: int = ModelField(required=False, format_=Format.BUTTONGROUP, depends=evens)

    sibling: ForwardRef('User') = None  # Self-referenced
    siblings: List[ForwardRef('User')] = None

    last_login: LastLogin = None
    logins: List[LastLogin] = None
    posts: List[Post] = None

    l: List[str] = None
    d: Dict[str, str] = None

    # Required is true by default, which means a user should have a team
    team: Team = RelationField(back_field_name='members', back_field_is_list=True, back_field_order=[('team_join_time', 1)])
    team_join_time: datetime = None

    update_time: datetime = None
    create_time: datetime = datetime.now

    __indexes__ = [{'fields': ['email'], 'unique': True}]
    __columns__ = ['avatar', 'name', 'status', 'roles', 'email', 'phone', 'create_time']
    __views__ = {
        'www://profile': '''#!form?title=User
            1#summary4,    2?title=User Info#8                                           
              avatar         name  
              name           phone                                                  
              status         intro                                                 
              roles          avatar                                                
              email        
              phone        
              create_time  
        ''',
    }
