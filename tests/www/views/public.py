""" public module. """
from datetime import datetime

from bson import ObjectId
from flask import Blueprint, render_template, current_app, redirect, request, abort, jsonify, url_for
from flask_login import current_user

from py3seed import populate_model, populate_search
from tests.core.models import User

public = Blueprint('public', __name__)


@public.route('/profile')
def profile():
    """ User. """
    pass
