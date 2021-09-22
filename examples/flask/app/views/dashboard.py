""" dashboard module. """
from datetime import datetime

from flask import Blueprint, render_template, current_app, redirect, request, abort, jsonify, url_for
from flask_login import current_user

from pyseed import populate_model, populate_search
from .common import get_id
from app.tools import auth_permission

dashboard = Blueprint('dashboard', __name__)


@dashboard.route('/home')
@auth_permission
def home():
    """ Get. """
    return render_template('dashboard/home.html')


@dashboard.route('/audit')
@auth_permission
def audit():
    """ Get. """
    id_ = get_id()
    if id_:
        user = User.find_one(id_)
        if not user:
            abort(404)
    else:
        user = User()
    #
    return render_template('dashboard/audit.html', user=user)


@dashboard.route('/audit/user.last_login-form', methods=('POST',))
@auth_permission
def audit_user.last_login-form():
    """ Post. """
    user = populate_model(request.form, User)
    id_ = get_id()
    if not id_:  # Create
        user.save()
        id_ = user._id
        current_app.logger.info(f'Successfully create User: {id_}')
    else:  # Update
        existing = User.find_one(id_)
        if not existing:
            abort(404)
        # TODO: Update fields in layout
        existing.updateTime = datetime.now()
        existing.save()
        current_app.logger.info(f'Successfully update User {id_}')
    #
    return jsonify(error=0, message=f'Save User successfully.', id=id_)
@dashboard.route('/profile')
@auth_permission
def profile():
    """ Get. """
    id_ = get_id()
    if id_:
        user = User.find_one(id_)
        if not user:
            abort(404)
    else:
        user = User()
    #
    return render_template('dashboard/profile.html', user=user)


@dashboard.route('/profile/user-form', methods=('POST',))
@auth_permission
def profile_user-form():
    """ Post. """
    user = populate_model(request.form, User)
    id_ = get_id()
    if not id_:  # Create
        user.save()
        id_ = user._id
        current_app.logger.info(f'Successfully create User: {id_}')
    else:  # Update
        existing = User.find_one(id_)
        if not existing:
            abort(404)
        # TODO: Update fields in layout
        existing.updateTime = datetime.now()
        existing.save()
        current_app.logger.info(f'Successfully update User {id_}')
    #
    return jsonify(error=0, message=f'Save User successfully.', id=id_)
