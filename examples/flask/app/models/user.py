# -*- coding: utf-8 -*-
"""
    user
    ~~~~~~~~~~~~~~

    User model.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/9/1
"""

from datetime import datetime
from typing import List

from pyseed import SimpleEnum, register, MongoModel, ModelField as Field, Format, BaseModel


class UserRole(SimpleEnum):
    """ User role. """
    MEMBER = 1
    EDITOR = 2
    ADMIN = 9


class UserStatus(SimpleEnum):
    """ User status. """
    NORMAL = 'normal'
    REJECTED = 'rejected'


class LastLogin(BaseModel):
    """ Last login of curernt user. """
    ip: str = Field(format_=Format.IP, required=False)
    location: str = Field(required=False)
    time: datetime

    __layout__ = '''
    ip, location
    time
    '''


@register
class User(MongoModel):
    """ User definition. """
    name: str
    email: str
    status: UserStatus = UserStatus.NORMAL
    roles: List[UserRole] = [UserRole.MEMBER]
    password: str = Field(format_=Format.PASSWORD)
    intro: str = Field(format_=Format.TEXTAREA, required=False)
    avatar: str = Field(format_=Format.AVATAR, required=False)
    #
    last_login: LastLogin = Field(required=False)
    #
    update_time: datetime = None
    create_time: datetime = datetime.now

    __indexes__ = [{'fields': ['email'], 'unique': True}]

    __columns__ = ['avatar', 'name', 'email', 'status', 'roles', 'create_time']
    __layout__ = '''
    avatar
    name, email
    status, roles
    password
    intro
    '''
