"""Tests for do/while loops and brace (aggregate) initializers.

Covers do/while semantics (body runs once, break, continue-to-condition), and
array/struct initializers in both automatic and static storage: positional,
partial (zero-filled), inferred array size, designated (`.field` and `[i]`),
nested aggregates, and scalar `= {x}`.
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


class TestDoWhile(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_run(
            "int main(){ int i=0,s=0; do { s+=i; i++; } while(i<5);"
            " return s; }"), 10)

    def test_runs_at_least_once(self):
        self.assertEqual(_run(
            "int main(){ int i=10; do { i++; } while(i<5); return i; }"), 11)

    def test_break(self):
        self.assertEqual(_run(
            "int main(){ int i=0; do { i++; if(i==3) break; } while(i<10);"
            " return i; }"), 3)

    def test_continue_goes_to_condition(self):
        self.assertEqual(_run(
            "int main(){ int i=0,s=0; do { i++; if(i==2) continue; s+=i; }"
            " while(i<4); return s; }"), 8)


class TestArrayInit(unittest.TestCase):
    def test_full(self):
        self.assertEqual(_run(
            "int main(){ int a[3]={10,20,12}; return a[0]+a[1]+a[2]; }"), 42)

    def test_partial_zero_filled(self):
        self.assertEqual(_run(
            "int main(){ int a[4]={1,2}; return a[0]+a[1]+a[2]+a[3]; }"), 3)

    def test_inferred_size(self):
        self.assertEqual(_run(
            "int main(){ int a[]={5,15,22};"
            " return a[0]+a[1]+a[2]+sizeof(a); }"), 54)

    def test_designated_index(self):
        self.assertEqual(_run(
            "int main(){ int a[5]={[2]=7,[4]=3}; return a[0]+a[2]+a[4]; }"),
            10)

    def test_char_array(self):
        self.assertEqual(_run(
            "int main(){ char s[3]={65,66,0}; return s[0]+s[1]; }"), 131)


class TestStructInit(unittest.TestCase):
    def test_positional(self):
        self.assertEqual(_run(
            "struct P{int x;int y;}; int main(){ struct P p={5,37};"
            " return p.x+p.y; }"), 42)

    def test_designated(self):
        self.assertEqual(_run(
            "struct P{int x;int y;}; int main(){ struct P p={.y=37,.x=5};"
            " return p.x+p.y; }"), 42)

    def test_scalar_in_braces(self):
        self.assertEqual(_run("int main(){ int x={42}; return x; }"), 42)

    def test_nested_array_of_structs(self):
        self.assertEqual(_run(
            "struct P{int x;int y;};"
            "int main(){ struct P a[3]={{1,2},{.y=10,.x=20},{7}};"
            " int s=0,i=0; do { s+=a[i].x+a[i].y; i++; } while(i<3);"
            " return s; }"), 40)


class TestStaticInit(unittest.TestCase):
    def test_static_zero(self):
        self.assertEqual(_run(
            "static int g[4]={0};"
            "int main(){ return g[0]+g[1]+g[2]+g[3]+1; }"), 1)

    def test_static_values(self):
        self.assertEqual(_run(
            "static int t[3]={7,14,21}; int main(){ return t[0]+t[1]+t[2]; }"),
            42)

    def test_static_struct_zero(self):
        self.assertEqual(_run(
            "struct P{int x;int y;}; static struct P p={0,0};"
            "int main(){ return p.x+p.y+9; }"), 9)


if __name__ == "__main__":
    unittest.main()
