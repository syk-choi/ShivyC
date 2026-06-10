"""Tests for the conditional (ternary) operator and constant folding.

Covers parsing + codegen of `cond ? a : b`: branch selection, that exactly one
arm is evaluated (side-effect test), right-associative nesting, use inside
larger expressions, and compile-time constant folding -- including the musl
idiom of a ternary as an array dimension, which also requires comparison
operators to fold to constants.
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


class TestConditional(unittest.TestCase):
    def test_true_arm(self):
        self.assertEqual(_run("int main(){ int x=1; return x ? 7 : 3; }"), 7)

    def test_false_arm(self):
        self.assertEqual(_run("int main(){ int x=0; return x ? 7 : 3; }"), 3)

    def test_only_one_arm_evaluated(self):
        # If both arms ran, n would end at 9 and the result would be 14.
        self.assertEqual(_run(
            "int main(){ int n=0; int r = 1 ? (n=5) : (n=9); return r+n; }"),
            10)

    def test_only_one_arm_evaluated_false(self):
        self.assertEqual(_run(
            "int main(){ int n=0; int r = 0 ? (n=5) : (n=9); return r+n; }"),
            18)

    def test_right_associative_nesting(self):
        self.assertEqual(_run(
            "int main(){ int a=2; return a==1 ? 10 : a==2 ? 20 : 30; }"), 20)

    def test_inside_arithmetic(self):
        self.assertEqual(_run(
            "int main(){ int x=1; return 100 + (x ? 2 : 5); }"), 102)

    def test_expression_in_middle(self):
        self.assertEqual(_run(
            "int main(){ int x=1; return x ? 2 + 3 : 0; }"), 5)


class TestConstantFolding(unittest.TestCase):
    def test_constant_condition_folds(self):
        self.assertEqual(_run("int main(){ return 1 ? 42 : 99; }"), 42)
        self.assertEqual(_run("int main(){ return 0 ? 42 : 99; }"), 99)

    def test_comparison_folds(self):
        self.assertEqual(_run(
            "int main(){ return (4 > 2) + (2 > 4) + (5 == 5); }"), 2)

    def test_ternary_as_array_size(self):
        self.assertEqual(_run(
            "int main(){ int a[1 == 1 ? 3 : 5];"
            " return sizeof(a)/sizeof(int); }"), 3)

    def test_musl_alltypes_array_idiom(self):
        # The exact shape used throughout musl's bits/alltypes.h. On this LP64
        # target sizeof(long)==8, so the array has 14 elements.
        self.assertEqual(_run(
            "int main(){ int a[sizeof(long) == 8 ? 14 : 9];"
            " return sizeof(a)/sizeof(int); }"), 14)


if __name__ == "__main__":
    unittest.main()
