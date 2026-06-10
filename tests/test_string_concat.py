"""Tests for adjacent string literal concatenation (C translation phase 6).

`"a" "b"` must lex/parse as a single literal `"ab"`. This matters especially
after macro expansion, where logging/assert macros prepend a prefix string
(e.g. `uk_pr_info("[INFO] " fmt, ...)`), producing two adjacent literals.
"""

import os
import subprocess
import tempfile
import unittest

import shivyc.main
from shivyc.errors import error_collector

_STRLEN = "int slen(const char *s){int n=0;while(s[n])n++;return n;}"


class _Args:
    show_reg_alloc_perf = False
    variables_on_stack = False
    simd_pack_globals = False
    stackless_calls = False
    metamorphic = False
    opt_level = 0

    def __init__(self, files, output_name):
        self.files = files
        self.output_name = output_name


def _run(source):
    workdir = tempfile.mkdtemp()
    c_path = os.path.join(workdir, "prog.c")
    out_path = os.path.join(workdir, "prog")
    with open(c_path, "w") as f:
        f.write(source)
    args = _Args([c_path], [out_path])
    shivyc.main.get_arguments = lambda: args
    error_collector.show = lambda: True
    error_collector.clear()
    rc = shivyc.main.main()
    assert rc == 0, "compilation failed"
    return subprocess.run([out_path]).returncode


class TestStringConcatenation(unittest.TestCase):
    def test_two_pieces(self):
        self.assertEqual(_run(
            _STRLEN + 'int main(){ return slen("ab" "cd"); }'), 4)

    def test_three_pieces(self):
        self.assertEqual(_run(
            _STRLEN + 'int main(){ return slen("ab" "cd" "e"); }'), 5)

    def test_content_is_joined(self):
        # m == "[INFO] hi"; first char '[' (91) + length 9 == 100.
        self.assertEqual(_run(
            _STRLEN + 'int main(){ const char *m = "[INFO] " "hi";'
            ' return m[0] + slen(m); }'), 100)

    def test_with_escape_between(self):
        # "AB" "\n" "C" -> 'A'+'B'+'\n'+'C' = 65+66+10+67
        self.assertEqual(_run(
            'int main(){ const char *m = "AB" "\\n" "C";'
            ' return m[0]+m[1]+m[2]+m[3]; }'), 208)

    def test_single_unaffected(self):
        self.assertEqual(_run(
            _STRLEN + 'int main(){ return slen("abcde"); }'), 5)

    def test_macro_prefix(self):
        # The motivating case: a macro prepends a prefix string.
        self.assertEqual(_run(
            '#define LOG(f) slen("[INFO] " f)\n'
            + _STRLEN +
            'int main(){ return LOG("hello"); }'), 12)


if __name__ == "__main__":
    unittest.main()
