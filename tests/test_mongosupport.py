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

from pyseed import DataError
from tests.test_model import User


def test_crud(db):
    """ Test cases for crud. """
    # Init
    assert User.delete_many({})
    assert User.count({}) == 0
    # C
    usr = User()
    usr.name = 'test'
    usr.email = 'test'
    usr.password = 'test'
    usr.save()
    assert User.count({}) == 1
    # R
    assert User.find_one({'name': 'test'}).name == 'test'

    # U
    del usr.name
    # Validation
    with pytest.raises(DataError, match='name') as excinfo:
        usr.save()
    # print(excinfo.value)

    usr.name = 'test1'
    # DulplicateKey from pymongo
    with pytest.raises(DuplicateKeyError) as excinfo:
        usr.save(insert_with_id=True)
    # print(excinfo.value)

    usr.save()
    assert User.find_one({'name': 'test1'}).name == 'test1'

    # D
    assert usr.delete().deleted_count == 1

    # Verify
    assert User.count({}) == 0
