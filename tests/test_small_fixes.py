"""Tests for several small C-conformance fixes:

* a label may be followed by a declaration (`done: int x = 0;`)
* stray semicolons at file scope are ignored (empty declarations)
* the GNU `, ##__VA_ARGS__` comma is removed when the variadic args are empty
* flexible array members (`struct { int n; int data[]; }`)
* `__builtin_expect(x, c)` evaluates to `x` (used by likely()/unlikely())
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


class TestLabelBeforeDeclaration(unittest.TestCase):
    def test_label_then_declaration(self):
        self.assertEqual(_run(
            "typedef unsigned long u64;"
            "int main(){ int x=0; if(x) goto f; f: u64 v=42; return (int)v; }"),
            42)

    def test_label_then_statement_still_works(self):
        self.assertEqual(_run(
            "int main(){ int i=0; top: i++; if(i<5) goto top; return i; }"), 5)


class TestStrayTopLevelSemicolon(unittest.TestCase):
    def test_after_function(self):
        self.assertEqual(_run(
            "int f(void){return 7;}; int main(){return f();};"), 7)

    def test_leading_and_trailing(self):
        self.assertEqual(_run(";;; int main(){return 9;};;"), 9)


class TestVariadicCommaRemoval(unittest.TestCase):
    def test_empty_then_nonempty(self):
        # C() -> cnt(0, -1) -> 0 args; C(7,8,9) -> 3 args.
        self.assertEqual(_run(
            "#include <stdarg.h>\n"
            "int cnt(int m, ...){ va_list ap; va_start(ap,m); int n=0,v;"
            " while((v=va_arg(ap,int))!=-1) n++; va_end(ap); return n; }\n"
            "#define C(...) cnt(0, ##__VA_ARGS__, -1)\n"
            "int main(){ return C()*10 + C(7,8,9); }"), 3)


class TestFlexibleArrayMember(unittest.TestCase):
    def test_size_excludes_fam(self):
        self.assertEqual(_run(
            "struct V{ unsigned short a; unsigned short b; unsigned short r[]; };"
            "int main(){ return sizeof(struct V); }"), 4)

    def test_access(self):
        self.assertEqual(_run(
            "struct V{ int n; int data[]; };"
            "int main(){ char buf[64]; struct V*v=(struct V*)buf;"
            " v->n=2; v->data[0]=30; v->data[1]=12;"
            " return v->data[0]+v->data[1]; }"), 42)

    def test_fam_offset(self):
        self.assertEqual(_run(
            "struct V{ unsigned short a; unsigned short b; unsigned short r[]; };"
            "int main(){ char buf[32]; struct V*v=(struct V*)buf;"
            " v->a=1; v->b=2; v->r[0]=40; return v->a + v->r[0]; }"), 41)

    def test_fam_must_be_last_rejected(self):
        rc, = (_compile(
            "struct V{ int data[]; int n; }; int main(){ return 0; }",
            os.path.join(tempfile.mkdtemp(), "p")),)
        self.assertNotEqual(rc, 0)


class TestBuiltinExpect(unittest.TestCase):
    def test_likely_unlikely(self):
        self.assertEqual(_run(
            "#define likely(x)   __builtin_expect(!!(x),1)\n"
            "#define unlikely(x) __builtin_expect(!!(x),0)\n"
            "int main(){ int n=42; if(likely(n>0) && !unlikely(n<0))"
            " return n; return 0; }"), 42)


if __name__ == "__main__":
    unittest.main()
