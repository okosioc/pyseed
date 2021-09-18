""" Common functions. """
import bson
from flask import request, abort

def get_id():
    """ Try to get model id from request.args and request.form.  """
    id_ = request.values.get('id')
    if id_:
        try:
            id_ = bson.ObjectId(id_)
        except bson.errors.InvalidId:
            abort(400)
    return id_