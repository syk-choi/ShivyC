"""Lexer-level tests for tokens that ShivyC previously could not produce.

These assert tokenization only -- e.g. ``?`` and ``:`` now lex as the
``question`` and ``colon`` token kinds, which unblocks tokenizing musl headers
(whose ``alltypes.h`` uses ternaries in array sizes such as
``int __i[sizeof(long)==8?14:9]``). Parsing a conditional *expression* is a
separate, later piece of work; this only covers the lexer.
"""

import unittest

import shivyc.lexer as lexer
import shivyc.token_kinds as token_kinds
from shivyc.errors import error_collector


def _kinds(src):
    error_collector.clear()
    toks = lexer.tokenize(src, "t.c")
    return [t.kind for t in toks], error_collector.issues


class TestTernaryTokens(unittest.TestCase):
    def test_question_and_colon_lex(self):
        kinds, issues = _kinds("a ? b : c")
        self.assertEqual(issues, [])
        self.assertIn(token_kinds.question, kinds)
        self.assertIn(token_kinds.colon, kinds)

    def test_ternary_packed_against_digits(self):
        # The exact musl idiom that used to produce "unrecognized token".
        kinds, issues = _kinds("int x[sizeof(long)==8?14:9];")
        self.assertEqual(issues, [])
        self.assertIn(token_kinds.question, kinds)
        self.assertIn(token_kinds.colon, kinds)


class TestIntegerConstantTokens(unittest.TestCase):
    def test_hex_binary_octal_suffix(self):
        for src in ("0x1F", "0b101", "010", "10UL", "42"):
            kinds, issues = _kinds(src)
            self.assertEqual(issues, [], "%r should lex" % src)
            self.assertEqual(kinds, [token_kinds.number], "%r" % src)


if __name__ == "__main__":
    unittest.main()
