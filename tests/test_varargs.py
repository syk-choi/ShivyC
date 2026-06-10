"""Tests for variadic function bodies: <stdarg.h>, va_list, va_start, va_arg.

ShivyC passes all arguments of a variadic function on the stack, so a va_list
is a moving pointer over the 8-byte argument slots. These exercise integer,
pointer, char (promoted), and mixed varargs, multiple named parameters before
the ellipsis, and passing a va_list to a helper that consumes it (the pattern
used by printf-style implementations).
"""

import os
import subprocess
import tempfile
import unittest

import shivyc.main
from shivyc.errors import error_collector

_SUM = ("#include <stdarg.h>\n"
        "int sum(int n, ...){ va_list ap; va_start(ap,n); int t=0;"
        " for(int i=0;i<n;i++) t+=va_arg(ap,int); va_end(ap); return t; }")


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


class TestVarargs(unittest.TestCase):
    def test_sum_three(self):
        self.assertEqual(_run(_SUM + "int main(){return sum(3,10,20,12);}"),
                         42)

    def test_sum_five(self):
        self.assertEqual(_run(
            _SUM + "int main(){return sum(5,1,2,3,4,5);}"), 15)

    def test_two_named_then_varargs(self):
        self.assertEqual(_run(
            "#include <stdarg.h>\n"
            "int f(int a,int b,...){ va_list ap; va_start(ap,b);"
            " int x=va_arg(ap,int); int y=va_arg(ap,int); va_end(ap);"
            " return a+b+x+y; }"
            "int main(){return f(1,2,3,4);}"), 10)

    def test_pointer_vararg(self):
        self.assertEqual(_run(
            "#include <stdarg.h>\n"
            "int slen(const char*s){int n=0;while(s[n])n++;return n;}"
            "int f(int n,...){ va_list ap; va_start(ap,n);"
            " const char*s=va_arg(ap,const char*); va_end(ap); return slen(s);}"
            "int main(){return f(1,\"hello!\");}"), 6)

    def test_char_vararg_promoted(self):
        self.assertEqual(_run(
            "#include <stdarg.h>\n"
            "int f(int n,...){ va_list ap; va_start(ap,n);"
            " char c=(char)va_arg(ap,int); va_end(ap); return c; }"
            "int main(){return f(1,65);}"), 65)

    def test_mixed_types(self):
        self.assertEqual(_run(
            "#include <stdarg.h>\n"
            "long f(int n,...){ va_list ap; va_start(ap,n);"
            " int a=va_arg(ap,int); long b=va_arg(ap,long);"
            " void*p=va_arg(ap,void*); va_end(ap); return a+b+(p!=0); }"
            "int main(){ int x; return (int)f(3,10,31L,&x); }"), 42)

    def test_valist_passed_to_helper(self):
        # va_start in one function, va_arg in a helper that receives the
        # va_list -- the printf/vprintf pattern.
        self.assertEqual(_run(
            "#include <stdarg.h>\n"
            "int consume(int n, va_list ap){ int t=0;"
            " for(int i=0;i<n;i++) t+=va_arg(ap,int); return t; }"
            "int f(int n,...){ va_list ap; va_start(ap,n);"
            " int r=consume(n,ap); va_end(ap); return r; }"
            "int main(){ return f(4,5,10,15,12); }"), 42)

    def test_gcc_style_builtins_direct(self):
        # The GCC-style spelling used by musl's <stdarg.h>:
        # __builtin_va_start / __builtin_va_arg / __builtin_va_end, with no
        # bundled stdarg.h macros in play.
        rc = _run(
            "typedef __builtin_va_list valist;\n"
            "static long sum(int n, ...){\n"
            "  valist ap; __builtin_va_start(ap, n);\n"
            "  long t = 0;\n"
            "  for (int i=0;i<n;i++) t += __builtin_va_arg(ap, int);\n"
            "  __builtin_va_end(ap); return t;\n"
            "}\n"
            "int main(){ return (int)sum(4, 10, 20, 30, 40); }\n")
        self.assertEqual(rc, 100)

    def test_gcc_style_va_copy(self):
        rc = _run(
            "typedef __builtin_va_list valist;\n"
            "static long twice(int n, ...){\n"
            "  valist ap, aq; __builtin_va_start(ap, n);\n"
            "  __builtin_va_copy(aq, ap);\n"
            "  long a=0,b=0;\n"
            "  for (int i=0;i<n;i++) a += __builtin_va_arg(ap, int);\n"
            "  for (int i=0;i<n;i++) b += __builtin_va_arg(aq, int);\n"
            "  __builtin_va_end(ap); __builtin_va_end(aq); return a+b;\n"
            "}\n"
            "int main(){ return (int)twice(3, 5, 10, 15); }\n")
        self.assertEqual(rc, 60)


if __name__ == "__main__":
    unittest.main()
