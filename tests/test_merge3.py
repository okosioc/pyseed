# -*- coding: utf-8 -*-
"""
    test_merge3
    ~~~~~~~~~~~~~~

    Test cases for merge3.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2023/7/7
"""

import sys
import struct

import pytest

from py3seed import merge3

int2byte = struct.Struct(">B").pack
from io import StringIO


def split_lines(t):
    return StringIO(t).readlines()


############################################################
# test case data from the gnu diffutils manual
# common base
TZU = split_lines("""     The Nameless is the origin of Heaven and Earth;
     The named is the mother of all things.

     Therefore let there always be non-being,
       so we may see their subtlety,
     And let there always be being,
       so we may see their outcome.
     The two are the same,
     But after they are produced,
       they have different names.
     They both may be called deep and profound.
     Deeper and more profound,
     The door of all subtleties!
""")

LAO = split_lines("""     The Way that can be told of is not the eternal Way;
     The name that can be named is not the eternal name.
     The Nameless is the origin of Heaven and Earth;
     The Named is the mother of all things.
     Therefore let there always be non-being,
       so we may see their subtlety,
     And let there always be being,
       so we may see their outcome.
     The two are the same,
     But after they are produced,
       they have different names.
""")

TAO = split_lines("""     The Way that can be told of is not the eternal Way;
     The name that can be named is not the eternal name.
     The Nameless is the origin of Heaven and Earth;
     The named is the mother of all things.

     Therefore let there always be non-being,
       so we may see their subtlety,
     And let there always be being,
       so we may see their result.
     The two are the same,
     But after they are produced,
       they have different names.

       -- The Way of Lao-Tzu, tr. Wing-tsit Chan

""")

MERGED_RESULT = split_lines(
    """     The Way that can be told of is not the eternal Way;
     The name that can be named is not the eternal name.
     The Nameless is the origin of Heaven and Earth;
     The Named is the mother of all things.
     Therefore let there always be non-being,
       so we may see their subtlety,
     And let there always be being,
       so we may see their result.
     The two are the same,
     But after they are produced,
       they have different names.
<<<<<<< LAO
=======

       -- The Way of Lao-Tzu, tr. Wing-tsit Chan

>>>>>>> TAO
""")


def test_no_changes():
    """ No conflicts because nothing changed. """
    m3 = merge3.Merge3(['aaa', 'bbb'],
                       ['aaa', 'bbb'],
                       ['aaa', 'bbb'])

    assert m3.find_unconflicted() == [(0, 2)]
    assert list(m3.find_sync_regions()) == [(0, 2, 0, 2, 0, 2), (2, 2, 2, 2, 2, 2)]
    assert list(m3.merge_regions()) == [('unchanged', 0, 2)]
    assert list(m3.merge_groups()) == [('unchanged', ['aaa', 'bbb'])]


def test_front_insert():
    """ OTHER inserts something at front of BASE, While THIS has no change. """
    m3 = merge3.Merge3([b'zz'],
                       [b'aaa', b'bbb', b'zz'],
                       [b'zz'])

    assert list(m3.find_sync_regions()) == [(0, 1, 2, 3, 0, 1), (1, 1, 3, 3, 1, 1)]
    assert list(m3.merge_regions()) == [('a', 0, 2), ('unchanged', 0, 1)]
    assert list(m3.merge_groups()) == [('a', [b'aaa', b'bbb']), ('unchanged', [b'zz'])]


def test_null_insert():
    """ OTHER inserts something to a null BASE, While THIS has no change. """
    m3 = merge3.Merge3([],
                       ['aaa', 'bbb'],
                       [])

    assert list(m3.find_sync_regions()) == [(0, 0, 2, 2, 0, 0)]
    assert list(m3.merge_regions()) == [('a', 0, 2)]
    assert list(m3.merge_groups()) == [('a', ['aaa', 'bbb'])]


def test_no_conflicts():
    """ No conflicts because only one side changed. """
    m3 = merge3.Merge3(['aaa', 'bbb'],
                       ['aaa', '111', 'bbb'],
                       ['aaa', 'bbb'])

    assert m3.find_unconflicted() == [(0, 1), (1, 2)]
    assert list(m3.find_sync_regions()) == [(0, 1, 0, 1, 0, 1),
                                            (1, 2, 2, 3, 1, 2),
                                            (2, 2, 3, 3, 2, 2), ]
    assert list(m3.merge_regions()) == [('unchanged', 0, 1),
                                        ('a', 1, 2),
                                        ('unchanged', 1, 2), ]


def test_append_a():
    """ OTHER appends something to BASE, While THIS has no change."""
    m3 = merge3.Merge3(['aaa\n', 'bbb\n'],
                       ['aaa\n', 'bbb\n', '222\n'],
                       ['aaa\n', 'bbb\n'])

    assert ''.join(m3.merge_lines()) == 'aaa\nbbb\n222\n'


def test_append_b():
    """ THIS appends something to BASE, While OTHER has no change. """
    m3 = merge3.Merge3(['aaa\n', 'bbb\n'],
                       ['aaa\n', 'bbb\n'],
                       ['aaa\n', 'bbb\n', '222\n'])

    assert ''.join(m3.merge_lines()) == 'aaa\nbbb\n222\n'


def test_append_agreement():
    """ BOTH append the same thing to BASE. """
    m3 = merge3.Merge3(['aaa\n', 'bbb\n'],
                       ['aaa\n', 'bbb\n', '222\n'],
                       ['aaa\n', 'bbb\n', '222\n'])

    assert ''.join(m3.merge_lines()) == 'aaa\nbbb\n222\n'


def test_append_clash():
    """ BOTH append different things to BASE. """
    m3 = merge3.Merge3(['aaa\n', 'bbb\n'],
                       ['aaa\n', 'bbb\n', '222\n'],
                       ['aaa\n', 'bbb\n', '333\n'])

    ml = m3.merge_lines(name_a='a',
                        name_b='b',
                        start_marker='<<',
                        mid_marker='--',
                        end_marker='>>')
    assert ''.join(ml) == '''\
aaa
bbb
<< a
222
--
333
>> b
'''


def test_insert_agreement():
    """ BOTH insert the same thing to BASE. """
    m3 = merge3.Merge3(['aaa\n', 'bbb\n'],
                       ['aaa\n', '222\n', 'bbb\n'],
                       ['aaa\n', '222\n', 'bbb\n'])

    ml = m3.merge_lines(name_a='a',
                        name_b='b',
                        start_marker='<<',
                        mid_marker='--',
                        end_marker='>>')
    assert ''.join(ml) == 'aaa\n222\nbbb\n'


def test_insert_clash():
    """ BOTH insert different things to BASE. """
    m3 = merge3.Merge3(['aaa\n', 'bbb\n'],
                       ['aaa\n', '111\n', 'bbb\n'],
                       ['aaa\n', '222\n', 'bbb\n'])

    assert m3.find_unconflicted() == [(0, 1), (1, 2)]
    assert list(m3.find_sync_regions()) == [(0, 1, 0, 1, 0, 1),
                                            (1, 2, 2, 3, 2, 3),
                                            (2, 2, 3, 3, 3, 3), ]
    assert list(m3.merge_regions()) == [('unchanged', 0, 1),
                                        ('conflict', 1, 1, 1, 2, 1, 2),
                                        ('unchanged', 1, 2)]
    assert list(m3.merge_groups()) == [('unchanged', ['aaa\n']),
                                       ('conflict', [], ['111\n'], ['222\n']),
                                       ('unchanged', ['bbb\n']),
                                       ]

    ml = m3.merge_lines(name_a='a',
                        name_b='b',
                        start_marker='<<',
                        mid_marker='--',
                        end_marker='>>')
    assert ''.join(ml) == '''\
aaa
<< a
111
--
222
>> b
bbb
'''


def test_replace_clash():
    """ Replacement with regions of same size """
    m3 = merge3.Merge3(['aaa\n', '000\n', 'bbb\n'],
                       ['aaa\n', '111\n', 'bbb\n'],
                       ['aaa\n', '222\n', 'bbb\n'])

    assert m3.find_unconflicted() == [(0, 1), (2, 3)]
    assert list(m3.find_sync_regions()) == [(0, 1, 0, 1, 0, 1),
                                            (2, 3, 2, 3, 2, 3),
                                            (3, 3, 3, 3, 3, 3), ]
    ml = m3.merge_lines(name_a='a',
                        name_b='b',
                        start_marker='<<',
                        mid_marker='--',
                        end_marker='>>')
    assert ''.join(ml) == '''\
aaa
<< a
111
--
222
>> b
bbb
'''


def test_replace_multi():
    """ Replacement with regions of different size."""
    m3 = merge3.Merge3([b'aaa', b'000', b'000', b'bbb'],
                       [b'aaa', b'111', b'111', b'111', b'bbb'],
                       [b'aaa', b'222', b'222', b'222', b'222', b'bbb'])

    assert m3.find_unconflicted() == [(0, 1), (3, 4)]
    assert list(m3.find_sync_regions()) == [(0, 1, 0, 1, 0, 1),
                                            (3, 4, 4, 5, 5, 6),
                                            (4, 4, 5, 5, 6, 6), ]


def test_merge_poem():
    """ Test case from diff3 manual. """
    m3 = merge3.Merge3(TZU, LAO, TAO)

    ml = list(m3.merge_lines('LAO', 'TAO'))
    assert ml == MERGED_RESULT


def test_merge_poem_bytes():
    """ Test case from diff3 manual. """
    m3 = merge3.Merge3(
        [line.encode() for line in TZU],
        [line.encode() for line in LAO],
        [line.encode() for line in TAO])

    ml = list(m3.merge_lines(b'LAO', b'TAO'))
    assert ml == [line.encode() for line in MERGED_RESULT]


def test_minimal_conflicts_common():
    """ Reprocessing. """
    base_text = ("a\n" * 20).splitlines(True)
    this_text = ("a\n" * 10 + "b\n" * 10).splitlines(True)
    other_text = ("a\n" * 10 + "c\n" + "b\n" * 8 + "c\n").splitlines(True)
    m3 = merge3.Merge3(base_text, other_text, this_text)

    m_lines = m3.merge_lines('OTHER', 'THIS', reprocess=True)
    merged_text = "".join(list(m_lines))
    optimal_text = (
            "a\n" * 10 + "<<<<<<< OTHER\nc\n"
                         "=======\n" + ">>>>>>> THIS\n" + 8 * "b\n" +
            "<<<<<<< OTHER\nc\n" + "=======\n" + 2 * "b\n" +
            ">>>>>>> THIS\n")
    assert optimal_text == merged_text


def test_minimal_conflicts_unique():
    """ Reprocessing. """

    def add_newline(s):
        """ Add a newline to each entry in the string. """
        return [(x + '\n') for x in s]

    base_text = add_newline("abcdefghijklm")
    this_text = add_newline("abcdefghijklmNOPQRSTUVWXYZ")
    other_text = add_newline("abcdefghijklm1OPQRSTUVWXY2")
    m3 = merge3.Merge3(base_text, other_text, this_text)
    m_lines = m3.merge_lines('OTHER', 'THIS', reprocess=True)
    merged_text = "".join(list(m_lines))
    optimal_text = ''.join(
        add_newline("abcdefghijklm")
        + ["<<<<<<< OTHER\n1\n=======\nN\n>>>>>>> THIS\n"]
        + add_newline('OPQRSTUVWXY')
        + ["<<<<<<< OTHER\n2\n=======\nZ\n>>>>>>> THIS\n"]
    )
    assert optimal_text == merged_text


def test_minimal_conflicts_nonunique():
    """ Reprocessing. """

    def add_newline(s):
        """ Add a newline to each entry in the string. """
        return [(x + '\n') for x in s]

    base_text = add_newline("abacddefgghij")
    this_text = add_newline("abacddefgghijkalmontfprz")
    other_text = add_newline("abacddefgghijknlmontfprd")
    m3 = merge3.Merge3(base_text, other_text, this_text)

    m_lines = m3.merge_lines('OTHER', 'THIS', reprocess=True)
    merged_text = "".join(list(m_lines))
    optimal_text = ''.join(
        add_newline("abacddefgghijk")
        + ["<<<<<<< OTHER\nn\n=======\na\n>>>>>>> THIS\n"]
        + add_newline('lmontfpr')
        + ["<<<<<<< OTHER\nd\n=======\nz\n>>>>>>> THIS\n"]
    )
    assert optimal_text == merged_text


def test_reprocess_and_base():
    """ Reprocessing and showing base breaks correctly. """
    base_text = ("a\n" * 20).splitlines(True)
    this_text = ("a\n" * 10 + "b\n" * 10).splitlines(True)
    other_text = ("a\n" * 10 + "c\n" + "b\n" * 8 + "c\n").splitlines(True)
    m3 = merge3.Merge3(base_text, other_text, this_text)

    m_lines = m3.merge_lines('OTHER', 'THIS', reprocess=True, base_marker='|||||||')
    pytest.raises(merge3.CantReprocessAndShowBase, list, m_lines)


def test_dos_text():
    """ Test DOS text. """
    base_text = 'a\r\n'
    this_text = 'b\r\n'
    other_text = 'c\r\n'
    m3 = merge3.Merge3(base_text.splitlines(True),
                       other_text.splitlines(True),
                       this_text.splitlines(True))

    m_lines = m3.merge_lines('OTHER', 'THIS')
    assert '<<<<<<< OTHER\r\nc\r\n=======\r\nb\r\n>>>>>>> THIS\r\n'.splitlines(True) == list(m_lines)


def test_mac_text():
    """ Text MAC text. """
    base_text = 'a\r'
    this_text = 'b\r'
    other_text = 'c\r'
    m3 = merge3.Merge3(base_text.splitlines(True),
                       other_text.splitlines(True),
                       this_text.splitlines(True))

    m_lines = m3.merge_lines('OTHER', 'THIS')
    assert '<<<<<<< OTHER\rc\r=======\rb\r>>>>>>> THIS\r'.splitlines(True), list(m_lines)


def test_merge3_cherrypick():
    """ Test cherry-pick merge. """
    base_text = "a\nb\n"
    this_text = "a\n"
    other_text = "a\nb\nc\n"
    # When cherrypicking, matches with b and base do not conflict, so a\nb is not in merge result
    m3 = merge3.Merge3(base_text.splitlines(True),
                       this_text.splitlines(True),
                       other_text.splitlines(True), is_cherrypick=True)

    m_lines = m3.merge_lines()
    assert 'a\n<<<<<<<\n=======\nc\n>>>>>>>\n' == ''.join(m_lines)

    # This is not symmetric
    m3 = merge3.Merge3(base_text.splitlines(True),
                       other_text.splitlines(True),
                       this_text.splitlines(True), is_cherrypick=True)

    m_lines = m3.merge_lines()
    assert 'a\n<<<<<<<\nb\nc\n=======\n>>>>>>>\n' == ''.join(m_lines)


def test_merge3_cherrypick_w_mixed():
    base_text = 'a\nb\nc\nd\ne\n'
    this_text = 'a\nb\nq\n'
    other_text = 'a\nb\nc\nd\nf\ne\ng\n'
    # When cherrypicking, lines in base are not part of the conflict
    m3 = merge3.Merge3(base_text.splitlines(True),
                       this_text.splitlines(True),
                       other_text.splitlines(True), is_cherrypick=True)
    m_lines = m3.merge_lines()
    assert 'a\n'
    'b\n'
    '<<<<<<<\n'
    'q\n'
    '=======\n'
    'f\n'
    '>>>>>>>\n'
    '<<<<<<<\n'
    '=======\n'
    'g\n'
    '>>>>>>>\n' == ''.join(m_lines)


def test_allow_objects():
    """ Objects other than strs may be used with Merge3.

    merge_groups and merge_regions work with non-str input.  Methods that
    return lines like merge_lines fail.
    """
    base = [(int2byte(x), int2byte(x)) for x in bytearray(b'abcde')]
    a = [(int2byte(x), int2byte(x)) for x in bytearray(b'abcdef')]
    b = [(int2byte(x), int2byte(x)) for x in bytearray(b'Zabcde')]
    m3 = merge3.Merge3(base, a, b)

    assert [('b', 0, 1),
            ('unchanged', 0, 5),
            ('a', 5, 6)] == list(m3.merge_regions())
    assert [('b', [(b'Z', b'Z')]),
            ('unchanged', [
                (int2byte(x), int2byte(x)) for x in bytearray(b'abcde')]),
            ('a', [(b'f', b'f')])] == list(m3.merge_groups())
