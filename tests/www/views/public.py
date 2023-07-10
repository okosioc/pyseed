""" public module. """
from flask import Blueprint, render_template, jsonify

public = Blueprint('public', __name__)


@public.route('/profile')
def profile():
    """ User. """
    return render_template('public/profile.html')


@public.route('/profile_create', methods=['POST'])
def profile_create():
    """ Post User. """
    return jsonify(error=0, message='OK')
