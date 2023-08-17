# -*- coding: utf-8 -*-
"""
    ext
    ~~~~~~~~~~~~~~

    Jinja2 extensions.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2023/8/10
"""
import re

from jinja2.exceptions import TemplateSyntaxError
from jinja2.ext import Extension
from jinja2.lexer import Token, count_newlines

_gettext_outside_re = re.compile(r"\\?(gettext|__)\(")
_gettext_inside_re = re.compile(r"\\?[()]")


class InlineGettext(Extension):
    """ This extension implements support for inline gettext blocks by __()::

        <h1>__(Welcome)</h1>
        <p>__(This is a paragraph)</p>

    Requires the i18n extension to be loaded and configured, it is only an simple alternative of gettext(), do not support ngettext()

    Thanks to https://jinja.palletsprojects.com/en/3.0.x/extensions/#inline-gettext
    """

    def filter_stream(self, stream):
        # parentheses stack
        paren_stack = 0

        for token in stream:
            if token.type != 'data':
                yield token
                continue

            pos = 0
            lineno = token.lineno

            while True:
                if not paren_stack:
                    match = _gettext_outside_re.search(token.value, pos)
                else:
                    match = _gettext_inside_re.search(token.value, pos)
                if match is None:
                    break
                new_pos = match.start()
                if new_pos > pos:
                    preval = token.value[pos:new_pos]
                    yield Token(lineno, 'data', preval)
                    lineno += count_newlines(preval)
                gtok = match.group()
                if gtok[0] == "\\":
                    yield Token(lineno, 'data', gtok[1:])
                elif not paren_stack:
                    yield Token(lineno, 'block_begin', None)
                    yield Token(lineno, 'name', 'trans')
                    yield Token(lineno, 'block_end', None)
                    paren_stack = 1
                else:
                    if gtok == "(" or paren_stack > 1:
                        yield Token(lineno, 'data', gtok)
                    paren_stack += -1 if gtok == ")" else 1
                    if not paren_stack:
                        yield Token(lineno, 'block_begin', None)
                        yield Token(lineno, 'name', 'endtrans')
                        yield Token(lineno, 'block_end', None)
                pos = match.end()

            if pos < len(token.value):
                yield Token(lineno, 'data', token.value[pos:])

        if paren_stack:
            raise TemplateSyntaxError(
                'unclosed inline gettext expression',
                token.lineno,
                stream.name,
                stream.filename,
            )


_getpro_re = re.compile(r"\$\$\((.*?)\)", re.DOTALL)


class InlineGetpro(Extension):
    """ This extension implements support for inline get pyseed property by $$()::

        <button>$$(text_search)</button> -> <button>{{ gerpro('text_search') }}</button>

    Need to put gerpro() into env firstly, this function load property by key from .pyseed-properties

    Thanks to https://github.com/pallets/jinja/blob/main/tests/test_ext.py#L187
    """

    def filter_stream(self, stream):
        for token in stream:
            if token.type == 'data':
                for t in self.interpolate(token):
                    yield t
            else:
                yield token

    def interpolate(self, token):
        pos = 0
        end = len(token.value)
        lineno = token.lineno
        while 1:
            match = _getpro_re.search(token.value, pos)
            if match is None:
                break
            value = token.value[pos:match.start()]
            if value:
                yield Token(lineno, 'data', value)
            lineno += count_newlines(token.value)
            yield Token(lineno, 'variable_begin', None)
            yield Token(lineno, 'name', 'getpro')
            yield Token(lineno, 'lparen', None)
            yield Token(lineno, 'string', match.group(1))
            yield Token(lineno, 'rparen', None)
            yield Token(lineno, 'variable_end', None)
            pos = match.end()
        if pos < end:
            yield Token(lineno, 'data', token.value[pos:])
