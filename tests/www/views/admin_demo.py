""" admin-demo module. """
from flask import Blueprint, render_template

admin_demo = Blueprint('admin_demo', __name__)


@admin_demo.route('/users')
def users():
    """ Users. """
    pass


