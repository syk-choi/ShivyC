"""Tests for `sizeof(struct/union tag)` and casts to tagged-struct pointers.

`sizeof(struct S)` and `(struct S *)p` previously forward-declared a fresh
*incomplete* `struct S` instead of reusing the existing complete definition,
so sizeof reported an incomplete type and a cast-then-dereference saw the
wrong (incomplete) type. These check that the existing tag is reused, while a
genuinely incomplete struct still reports an error.
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


def _compile(source):
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
    return rc, out_path


def _run(source):
    rc, out_path = _compile(source)
    assert rc == 0, "compilation failed"
    return subprocess.run([out_path]).returncode


class TestSizeofTag(unittest.TestCase):
    def test_sizeof_struct_tag(self):
        self.assertEqual(_run(
            "struct S{int a;int b;}; int main(){ return sizeof(struct S); }"),
            8)

    def test_sizeof_in_expression(self):
        self.assertEqual(_run(
            "struct S{int a;int b;};"
            "int main(){ return sizeof(struct S)*4 - 31; }"), 1)

    def test_sizeof_nested_struct(self):
        self.assertEqual(_run(
            "struct E{int v;}; struct S{struct E e; int b;};"
            "int main(){ return sizeof(struct S); }"), 8)

    def test_sizeof_used_as_offset(self):
        self.assertEqual(_run(
            "struct H{int a;int b;};"
            "int main(){ char buf[100]; char *d = buf + sizeof(struct H);"
            " return (int)(d - buf); }"), 8)

    def test_genuinely_incomplete_still_errors(self):
        # `struct S;` with no definition has no size; sizeof must fail.
        rc, _ = _compile(
            "struct S; int main(){ return sizeof(struct S); }")
        self.assertNotEqual(rc, 0)


class TestCastToTaggedPointer(unittest.TestCase):
    def test_cast_struct_pointer_and_deref(self):
        # The cast must reuse the complete struct so `q->len` is valid.
        self.assertEqual(_run(
            "struct N{int len;int cap;};"
            "int main(){ struct N n; n.len=42; void *p=&n;"
            " struct N *q=(struct N *)p; return q->len; }"), 42)


if __name__ == "__main__":
    unittest.main()
