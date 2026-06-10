"""Tests for enum types, goto/labels, and empty translation units.

These exercise enumerator value assignment (implicit, explicit, expression,
negative), anonymous enums, using an enum as a type and in constant contexts,
forward/backward/cross-block goto, and a comment-only (token-less) file, which
previously crashed the parser with an IndexError.
"""

import os
import subprocess
import tempfile
import unittest

import shivyc.main
from shivyc.errors import error_collector


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


def _compile(source, out_path):
    workdir = tempfile.mkdtemp()
    c_path = os.path.join(workdir, "prog.c")
    with open(c_path, "w") as f:
        f.write(source)
    args = _Args([c_path], [out_path])
    shivyc.main.get_arguments = lambda: args
    error_collector.show = lambda: True
    error_collector.clear()
    return shivyc.main.main()


def _run(source):
    out_path = os.path.join(tempfile.mkdtemp(), "prog")
    rc = _compile(source, out_path)
    assert rc == 0, "compilation failed"
    return subprocess.run([out_path]).returncode


class TestEnum(unittest.TestCase):
    def test_implicit_values(self):
        self.assertEqual(_run(
            "enum E{A,B,C,D}; int main(){ return A + B*1 + C*10 + D*100; }"),
            65)

    def test_explicit_and_resumed(self):
        self.assertEqual(_run(
            "enum E{A=5,B,C=10,D}; int main(){ return A+B+C+D; }"), 32)

    def test_expression_values(self):
        self.assertEqual(_run(
            "enum E{X=1+2,Y=X*2,Z=Y-1};"
            "int main(){ return X*100+Y*10+Z; }"), 109)

    def test_negative_value(self):
        self.assertEqual(_run(
            "enum E{N=-3,M}; int main(){ return (M-N)+10; }"), 11)

    def test_anonymous(self):
        self.assertEqual(_run(
            "enum {FOO=42}; int main(){ return FOO; }"), 42)

    def test_as_type_and_sizeof(self):
        self.assertEqual(_run(
            "enum C{R,G,B}; int main(){ enum C c=G; return c+sizeof(enum C); }"
        ), 5)

    def test_as_array_size(self):
        self.assertEqual(_run(
            "enum {N=4}; int main(){ int a[N]; a[3]=7; return a[3]+N; }"), 11)

    def test_in_switch_case(self):
        self.assertEqual(_run(
            "enum {OPT=2}; int main(){ int x=2,r=0;"
            " switch(x){ case OPT: r=9; break; } return r; }"), 9)


class TestGoto(unittest.TestCase):
    def test_backward(self):
        self.assertEqual(_run(
            "int main(){ int i=0,s=0; loop: s+=i; i++;"
            " if(i<5) goto loop; return s; }"), 10)

    def test_forward_skip(self):
        self.assertEqual(_run(
            "int main(){ int r=0; goto skip; r=100; skip: r+=5; return r; }"),
            5)

    def test_exit_nested_loops(self):
        self.assertEqual(_run(
            "int main(){ int i,j,f=0;"
            " for(i=0;i<5;i++){ for(j=0;j<5;j++){"
            " if(i*j==6){ f=i*10+j; goto done; } } } done: return f; }"), 23)

    def test_multiple_labels(self):
        self.assertEqual(_run(
            "int main(){ int r=0; goto a; b: r+=2; goto end;"
            " a: r+=1; goto b; end: return r; }"), 3)


class TestEmptyTranslationUnit(unittest.TestCase):
    def test_comment_only_file_does_not_crash(self):
        # A file with no tokens must compile to assembly without crashing.
        # (It has no `main`, so we only require the front-end to succeed, not
        # a successful executable link.)
        out_path = os.path.join(tempfile.mkdtemp(), "empty")
        try:
            _compile("/* only a comment */\n", out_path)
        except IndexError:
            self.fail("empty translation unit crashed the parser")


if __name__ == "__main__":
    unittest.main()
