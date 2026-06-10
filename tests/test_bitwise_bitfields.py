"""Tests for bitwise operators, bitfields, and GCC extension shims.

Bitwise `& | ^` were entirely absent from ShivyC (the `|`/`^` tokens did not
even exist); these tests cover the operators, their precedence, and constant
folding. Bitfields build on them: each field is masked to its declared width
on write and on read (with sign-extension for signed fields). The attribute
tests confirm that GCC extension spellings used throughout library headers are
accepted (and ignored) rather than causing parse errors.
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


class TestBitwise(unittest.TestCase):
    def test_and_or_xor(self):
        self.assertEqual(_run("int main(){ return 6 & 3; }"), 2)
        self.assertEqual(_run("int main(){ return 4 | 1; }"), 5)
        self.assertEqual(_run("int main(){ return 5 ^ 1; }"), 4)

    def test_precedence(self):
        # & binds tighter than ^ which binds tighter than |.
        self.assertEqual(_run("int main(){ return 1 | 2 & 2; }"), 3)
        self.assertEqual(_run("int main(){ return 1 ^ 3 | 4; }"), 6)

    def test_distinct_from_logical(self):
        # `&` vs `&&`: 1&2 == 0 but 1&&2 == 1.
        self.assertEqual(
            _run("int main(){ int a=1,b=2; return (a && b) + (a & b); }"), 1)

    def test_runtime_mask(self):
        self.assertEqual(
            _run("int main(){ int x=0xFF, m=0x0F; return x & m; }"), 15)

    def test_address_of_still_works(self):
        self.assertEqual(
            _run("int main(){ int v=42; int *p=&v; return *p; }"), 42)

    def test_folding_in_array_size(self):
        self.assertEqual(_run(
            "int main(){ int a[(6 & 3) | 4]; return sizeof(a)/sizeof(int); }"),
            6)


class TestBitfields(unittest.TestCase):
    def test_named_read_write(self):
        self.assertEqual(_run(
            "struct S { unsigned a:3; unsigned b:5; };"
            "int main(){ struct S s; s.a=2; s.b=20; return s.a + s.b; }"), 22)

    def test_unsigned_truncation(self):
        self.assertEqual(_run(
            "struct S { unsigned a:3; };"
            "int main(){ struct S s; s.a=9; return s.a; }"), 1)

    def test_signed_sign_extension(self):
        self.assertEqual(_run(
            "struct S { int x:4; };"
            "int main(){ struct S s; s.x=-3; return s.x + 10; }"), 7)

    def test_signed_truncation(self):
        # 5 stored in a 3-bit signed field reads back as -3.
        self.assertEqual(_run(
            "struct S { int x:3; };"
            "int main(){ struct S s; s.x=5; return s.x + 10; }"), 7)

    def test_fields_independent(self):
        self.assertEqual(_run(
            "struct S { unsigned a:4; unsigned b:4; };"
            "int main(){ struct S s; s.a=15; s.b=15;"
            " return (s.a==15)+(s.b==15); }"), 2)

    def test_pointer_member(self):
        self.assertEqual(_run(
            "struct S { unsigned a:3; };"
            "int main(){ struct S s; struct S *p=&s; p->a=5; return p->a; }"),
            5)

    def test_anonymous_zero_width(self):
        self.assertEqual(_run(
            "struct S { int a; int :0; int b; };"
            "int main(){ struct S s; s.a=3; s.b=4; return s.a + s.b; }"), 7)

    def test_anonymous_padding(self):
        self.assertEqual(_run(
            "struct S { char a; int :8; char b; };"
            "int main(){ struct S s; s.a=3; s.b=4; return s.a + s.b; }"), 7)

    def test_musl_timespec_idiom(self):
        # struct timespec uses an anonymous bitfield whose width is a constant
        # expression; on LP64 the width is 0.
        self.assertEqual(_run(
            "struct timespec { long tv_sec;"
            " int :8*(sizeof(long)-sizeof(long)); long tv_nsec; };"
            "int main(){ struct timespec t; t.tv_sec=5; t.tv_nsec=9;"
            " return t.tv_sec + t.tv_nsec; }"), 14)


class TestAttributeShims(unittest.TestCase):
    def test_attribute_on_variable(self):
        self.assertEqual(_run(
            "int x __attribute__((aligned(16))) = 5; int main(){ return x; }"),
            5)

    def test_may_alias_typedef(self):
        self.assertEqual(_run(
            "typedef unsigned u32 __attribute__((__may_alias__));"
            "int main(){ u32 x = 9; return x; }"), 9)

    def test_restrict_and_extension(self):
        self.assertEqual(_run(
            "__extension__ int f(int *__restrict p){ return *p; }"
            "int main(){ int v=4; return f(&v); }"), 4)


if __name__ == "__main__":
    unittest.main()
