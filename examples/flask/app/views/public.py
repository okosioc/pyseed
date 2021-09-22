""" public module. """
from datetime import datetime

from flask import Blueprint, render_template, current_app, redirect, request, abort, jsonify, url_for
from flask_login import current_user

from pyseed import populate_model, populate_search
from .common import get_id
from app.tools import auth_permission

public = Blueprint('public', __name__)


@public.route('/post')
def post():
    """ Get. """
    return render_template('public/post.html')


@public.route('/signup')
def signup():
    """ Get. """
    return render_template('public/signup.html')


@public.route('/blog')
def blog():
    """ Get. """
    return render_template('public/blog.html')


@public.route('/index')
def index():
    """ Get. """
    return render_template('public/index.html')


@public.route('/login')
def login():
    """ Get. """
    return render_template('public/login.html')


