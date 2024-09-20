# -*- coding: utf-8 -*-
"""
    test_gen
    ~~~~~~~~~~~~~~

    Gen test cases.

    :copyright: (c) 2023 by weiminfeng.
    :date: 2023/5/29
"""
import os

import pytest

from py3seed import LayoutError
from py3seed.utils import parse_layout, get_layout_fields
from py3seed.commands.gen import _gen
from .core.models import User, Team, Tag


def test_layout_parsing():
    """ Test layout parsing. """
    # Testing layouts
    # NOTE: Below layouts just for layout parse tests, not for gen test cases
    user_profile_layout = '''#!form?title=User
        1#summary4,    2#8                                           
          avatar         name  
          name           phone                                                  
          status         intro                                                 
          roles          avatar                                                
          email          point#4,
          phone
          create_time
    '''
    team_members_layout = '''#!read?title=Members
        1#summary,     members#8                                                  
          logo           avatar, name, status, roles, email, phone, team_join_time
          name         
          phone                                                                
          members                                                                   
          create_time
    '''
    # Schemas
    user_schema = User.schema()
    team_schema = Team.schema()

    #
    # Validation
    #

    # Validate invalid indent
    with pytest.raises(LayoutError) as exc_info:
        parse_layout(
            user_profile_layout.replace('status', ' status'),
            user_schema,
        )
    #
    assert 'indent' in str(exc_info.value)
    # Validate invalid field name
    with pytest.raises(LayoutError) as exc_info:
        parse_layout(
            user_profile_layout.replace('create_time', 'creat_time'),
            user_schema,
        )
    #
    assert 'creat_time not found' in str(exc_info.value)
    # Validate simple field that having inner layout
    with pytest.raises(LayoutError) as exc_info:
        parse_layout(
            user_profile_layout.replace('intro', '  intro'),
            user_schema,
        )
    #
    assert 'phone can not have inner layout' in str(exc_info.value)

    #
    # Parsing
    #

    # User profile layout
    layout = parse_layout(user_profile_layout, user_schema)
    assert layout['action'] == 'form'
    assert layout['params']['title'] == 'User'
    assert len(layout['rows']) == 1
    first_row = layout['rows'][0]
    assert first_row[0]['name'] == '1'
    assert first_row[0]['format'] == 'summary'
    assert first_row[0]['span'] == 4
    assert len(first_row[0]['rows']) == 7
    assert first_row[0]['rows'][0][0]['name'] == 'avatar'
    assert len(first_row[1]['rows']) == 5
    assert first_row[1]['rows'][1][0]['name'] == 'phone'
    assert first_row[1]['rows'][4][0]['name'] == 'point'
    assert first_row[1]['rows'][4][0]['span'] == 4
    assert first_row[1]['rows'][4][1]['name'] == ''
    assert list(get_layout_fields(layout['rows'])) == ['name', 'phone', 'intro', 'avatar', 'point']

    # Team member layout
    layout = parse_layout(team_members_layout, team_schema)
    assert layout['action'] == 'read'
    first_row = layout['rows'][0]
    assert first_row[0]['span'] is None
    assert first_row[0]['format'] == 'summary'
    assert len(first_row[1]['rows'][0]) == 7
    assert first_row[1]['rows'][0][0]['name'] == 'avatar'

    #
    # Test recursively parsing
    #
    tag_read_layout = '''#!read?title=Tags
          name
          albums
            cover, title, tags
    '''
    tag_schema = Tag.schema()
    layout = parse_layout(tag_read_layout, tag_schema)
    assert layout['action'] == 'read'
    second_row = layout['rows'][1]
    assert second_row[0]['name'] == 'albums'
    assert second_row[0]['rows'][0][0]['name'] == 'cover'
    assert second_row[0]['rows'][0][2]['name'] == 'tags'
    assert second_row[0]['rows'][0][2]['name'] == 'tags'


def test_gen():
    """ Test Generation. """
    # Change working folder
    os.chdir('tests')
    #
    # Init
    #
    # Prepare team-members.html*, which is used to test 3-way merge with conflicts
    # We need to remove the outstanding files generated in last test run
    try:
        os.remove('www/templates/public/team-members.html.BASE')
        os.remove('www/templates/public/team-members.html.THIS')
        os.remove('www/templates/public/team-members.html.OTHER')
        #
        os.remove('www/views/admin_demo.py')
    except FileNotFoundError:
        pass
    # Then manually init BASE and THIS file, otherwise then will be overwritten during each test
    base = '''<html>
<head>
    <title>Members</title>
</head>
<body>
    <h1 class="base">Members</h1>
    <h2>read</h2>
    <div class="row">
        <div class="column">1</div>
        <div class="column">members</div>
    </div>
</body>
</html>'''
    #
    with open('www/templates/public/team-members.html.1', 'w', encoding='utf-8') as f:
        f.write(base)
    #
    this = '''<html>
<head>
    <title>Members</title>
</head>
<body>
    <h1 class="this">Members</h1>
    <h2>read</h2>
    <div class="row">
        <div class="column">1</div>
        <div class="column">members</div>
    </div>
</body>
</html>'''
    with open('www/templates/public/team-members.html', 'w', encoding='utf-8') as f:
        f.write(this)
    #
    # Generate
    #
    _gen()
    #
    # Test Cases
    #
    # public.py should be not changed, as public.py.0 exsits
    public_py = open('www/views/public.py', encoding='utf-8').read()
    assert public_py == '''""" public module. """
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
'''
    # profile.html should be 3-way merged
    # We add class="page-header" to h1 tag manually, this should be kept after merging
    profile_html = open('www/templates/public/profile.html', encoding='utf-8').read()
    assert profile_html == '''<html>
<head>
    <title>User</title>
</head>
<body>
    <h1 class="page-header">User</h1>
    <h2>form</h2>
    <div class="row">
        <div class="column">1</div>
        <div class="column">2</div>
    </div>
</body>
</html>'''
    # team-members.html should be 3-way merged with conflicts
    team_members_html = open('www/templates/public/team-members.html', encoding='utf-8').read()
    assert team_members_html == '''<html>
<head>
    <title>Members</title>
</head>
<body>
<<<<<<< OTHER
    <h1>Members</h1>
=======
    <h1 class="this">Members</h1>
>>>>>>> THIS
    <h2>read</h2>
    <div class="row">
        <div class="column">1</div>
        <div class="column">members</div>
    </div>
</body>
</html>'''
    # enum.js should be rendered every time
    enums_js = open('www/static/js/enums.js', encoding='utf-8').read()
    assert enums_js == '''//
// Enums
//

var global_enums = {
UserStatus: {'normal': 'Normal', 'rejected': 'Rejected'},
UserRole: {1: 'Member', 2: 'Editor', 9: 'Admin'},
}
'''
    # py naming convention, for blueprint whose name is kebab-case, e.g, www://admin-demo/user-list
    # when {{#blueprint}}.py.jinja2 is rendered, the file name should be admin_demo.py, instead of admin-demo.py
    assert os.path.exists('www/views/admin_demo.py')

    # global functions
    render_env_txt = open('www/templates/render_env.txt', encoding='utf-8').read()
    assert 'iamhere.html: True' in render_env_txt
    assert 'User title fields: [\'name\']' in render_env_txt
    assert 'User title field: name' in render_env_txt
    assert 'text_welcome: 欢迎' in render_env_txt
    assert '$text_welcome: 欢迎' in render_env_txt
