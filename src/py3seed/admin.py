# -*- coding: utf-8 -*-
"""
    admin
    ~~~~~~~~~~~~~~

    Admin support.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/9/2
"""

# ----------------------------------------------------------------------------------------------------------------------
# Register models into seed admin.
#

registered_models = []


def register(models):
    """ Register model to seed admin, can use it as a decorator on BaseModel. """

    # Enable decorator usage
    decorator = None
    if not isinstance(models, (list, tuple, set, frozenset)):
        # We assume that the user used this as a decorator
        # using @register syntax or using db.register(Model)
        # we stock the class object in order to return it later
        decorator = models
        models = [models]

    for model_ in models:
        if model_ not in registered_models:
            registered_models.append(model_)

    if decorator is None:
        return registered_models
    else:
        return decorator
