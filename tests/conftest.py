# -*- coding: utf-8 -*-
"""
    conftest
    ~~~~~~~~~~~~~~

    Sharing fixture functions.

    :copyright: (c) 2021 by fengweimin.
    :date: 2021/8/11
"""

import pytest

from py3seed import connect


@pytest.fixture(scope='module')
def db():
    """ 准备数据库. """
    # 匿名访问本地数据库, 无需实现创建
    connect('mongodb://localhost:27017/pytest')
    # 需要用户密码访问, 需要先设置用户名密码
    # mongo
    # use encrypted_pytest
    # db.createUser({user:"mongousr1",pwd:"5t6yh7ujm*USR",roles:["readWrite"]})
    # connect('mongodb://mongousr1:5t6yh7ujm*USR@localhost:27017/encrypted_pytest')
