# -*- coding: utf-8 -*-
"""
    error
    ~~~~~~~~~~~~~~

    Error defintion.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/6/9
"""


class SeedError(Exception):
    """ Base class for exceptions. """

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class SchemaError(SeedError):
    """ Schema error. """
    pass


class PathError(SeedError):
    """ Path error. """
    pass


class DataError(SeedError):
    """ Data error. """
    pass


class DatabaseError(SeedError):
    """ Database error. """
    pass


class TemplateError(SeedError):
    """ Template error. """
    pass
