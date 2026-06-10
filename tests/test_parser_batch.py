"""Tests for the small parser/codegen features added to unblock Minikraft:

* compound bitwise/shift assignment (`|= &= ^= <<= >>=`)
* variadic function prototypes (`f(int, ...)`)
* the conditional operator's pointer result type (pointer vs NULL / void* /
  compatible pointers)
* switch / case / default (including fall-through and default)
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


class TestCompoundBitwiseAssign(unittest.TestCase):
    def test_or_and_xor(self):
        self.assertEqual(_run("int main(){ int x=0x10; x|=2; return x; }"), 18)
        self.assertEqual(_run("int main(){ int x=0xFF; x&=0xF; return x; }"),
                         15)
        self.assertEqual(_run("int main(){ int x=0xF; x^=5; return x; }"), 10)

    def test_shifts(self):
        self.assertEqual(_run("int main(){ int x=3; x<<=4; return x; }"), 48)
        self.assertEqual(_run("int main(){ int x=64; x>>=2; return x; }"), 16)

    def test_chained_flags(self):
        self.assertEqual(_run(
            "int main(){ int c=0; c|=0x02; c|=0x40; return c; }"), 66)


class TestVariadicPrototype(unittest.TestCase):
    def test_prototype_parses(self):
        self.assertEqual(_run(
            "extern void printk(const char *fmt, ...);"
            "int main(void){ return 5; }"), 5)

    def test_two_named_then_ellipsis(self):
        self.assertEqual(_run(
            "int f(int a, int b, ...); int main(void){ return 7; }"), 7)


class TestConditionalPointer(unittest.TestCase):
    def test_pointer_or_null(self):
        self.assertEqual(_run(
            "int main(){ int v=42; int *p=&v; int *q = p ? p : 0;"
            " return *q; }"), 42)

    def test_pointer_or_NULL(self):
        self.assertEqual(_run(
            "#include <stddef.h>\n"
            "int main(){ int v=42; int *p=&v; int *q = p ? p : NULL;"
            " return *q; }"), 42)

    def test_void_pointer(self):
        self.assertEqual(_run(
            "int main(){ int v=7; void *vp=&v; int *p=&v;"
            " void *r = 1 ? vp : p; return *(int *)r; }"), 7)


class TestSwitch(unittest.TestCase):
    def test_basic_match(self):
        self.assertEqual(_run(
            "int main(){ int x=2,r=0; switch(x){ case 1: r=10; break;"
            " case 2: r=20; break; default: r=99; } return r; }"), 20)

    def test_default(self):
        self.assertEqual(_run(
            "int main(){ int x=7,r=0; switch(x){ case 1: r=10; break;"
            " default: r=42; } return r; }"), 42)

    def test_fall_through(self):
        self.assertEqual(_run(
            "int main(){ int x=1,r=0; switch(x){ case 1: r+=1; case 2: r+=10;"
            " case 3: r+=100; break; case 4: r=999; } return r; }"), 111)

    def test_no_match_no_default(self):
        self.assertEqual(_run(
            "int main(){ int x=5,r=0; switch(x){ case 1: r=1; break; }"
            " return r; }"), 0)


if __name__ == "__main__":
    unittest.main()
