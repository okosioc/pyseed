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
    connect('mongodb://localhost:27017/pytest')
