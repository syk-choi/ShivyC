"""Tests for passing function arguments on the stack (SysV AMD64).

ShivyC previously crashed on any function with more than six integer
parameters (only the six argument registers were supported). These tests
exercise 7-10 arguments across the default code path and the optimization
paths that change the stack frame (`-fstackless-calls` and `-O4`, which enable
tail calls / frameless functions / metamorphic returns), since those interact
with stack-argument alignment and the `[rbp+16]` argument loads.
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

    def __init__(self, files, output_name, stackless=False, opt_level=0,
                 metamorphic=False):
        self.files = files
        self.output_name = output_name
        self.stackless_calls = stackless
        self.opt_level = opt_level
        self.metamorphic = metamorphic


def _run(source, **flags):
    workdir = tempfile.mkdtemp()
    c_path = os.path.join(workdir, "prog.c")
    out_path = os.path.join(workdir, "prog")
    with open(c_path, "w") as f:
        f.write(source)
    args = _Args([c_path], [out_path], **flags)
    shivyc.main.get_arguments = lambda: args
    error_collector.show = lambda: True
    error_collector.clear()
    rc = shivyc.main.main()
    assert rc == 0, "compilation failed"
    return subprocess.run([out_path]).returncode


_SUM7 = ("int f(int a,int b,int c,int d,int e,int g,int h)"
         "{return a+b+c+d+e+g+h;}")


class TestStackArgsDefault(unittest.TestCase):
    def test_seven(self):
        self.assertEqual(_run(_SUM7 + "int main(){return f(1,2,3,4,5,6,7);}"),
                         28)

    def test_ten(self):
        self.assertEqual(_run(
            "int f(int a,int b,int c,int d,int e,int g,int h,int i,int j,"
            "int k){return k-a;} int main(){return f(1,2,3,4,5,6,7,8,9,40);}"),
            39)

    def test_seventh_arg_value(self):
        self.assertEqual(_run(
            "int f(int a,int b,int c,int d,int e,int g,int h){return h*2;}"
            "int main(){return f(0,0,0,0,0,0,21);}"), 42)

    def test_mixed_sizes(self):
        self.assertEqual(_run(
            "long f(char a,long b,int c,char d,long e,int g,long h)"
            "{return (long)a+b+c+d+e+g+h;}"
            "int main(){return (int)f(1,2,3,4,5,6,21);}"), 42)

    def test_pointer_args(self):
        self.assertEqual(_run(
            "int f(int*a,int*b,int*c,int*d,int*e,int*g,int*h){return *a+*h;}"
            "int main(){int v1=2,v2=40;"
            " return f(&v1,&v1,&v1,&v1,&v1,&v1,&v2);}"), 42)

    def test_indirect_call(self):
        self.assertEqual(_run(
            _SUM7 + "int main(){int(*fp)(int,int,int,int,int,int,int)=f;"
            " return fp(1,2,3,4,5,6,7);}"), 28)

    def test_recursion_through_seven_args(self):
        self.assertEqual(_run(
            "int f(int n,int a,int b,int c,int d,int e,int g){"
            " if(n==0) return a+b+c+d+e+g; return f(n-1,a+1,b,c,d,e,g);}"
            "int main(){return f(5,0,1,2,3,4,5);}"), 20)

    def test_nested_calls(self):
        self.assertEqual(_run(
            "int g(int a,int b,int c,int d,int e,int f,int h){return a+h;}"
            "int top(int a,int b,int c,int d,int e,int f,int h){"
            " return g(a,b,c,d,e,f,h)+h;}"
            "int main(){return top(1,2,3,4,5,6,7);}"), 15)


class TestStackArgsStackless(unittest.TestCase):
    def test_seven_args(self):
        self.assertEqual(_run(_SUM7 + "int main(){return f(1,2,3,4,5,6,7);}",
                              stackless=True), 28)

    def test_tail_position_seven_args(self):
        # A 7-arg call in tail position must NOT be tail-eliminated.
        self.assertEqual(_run(
            "int helper(int a,int b,int c,int d,int e,int g,int h)"
            "{return a+h;}"
            "int f(int a,int b,int c,int d,int e,int g,int h)"
            "{return helper(a,b,c,d,e,g,h);}"
            "int main(){return f(1,2,3,4,5,6,40);}", stackless=True), 41)


class TestStackArgsO4(unittest.TestCase):
    def test_seven_args(self):
        self.assertEqual(_run(_SUM7 + "int main(){return f(1,2,3,4,5,6,7);}",
                              opt_level=4, metamorphic=True), 28)

    def test_recursion_eight_args(self):
        self.assertEqual(_run(
            "int f(int n,int a,int b,int c,int d,int e,int g,int h){"
            " if(n==0) return a+h; return f(n-1,a+1,b,c,d,e,g,h);}"
            "int main(){return f(3,0,0,0,0,0,0,39);}",
            opt_level=4, metamorphic=True), 42)


if __name__ == "__main__":
    unittest.main()
