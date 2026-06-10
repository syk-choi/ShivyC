"""Tests for static initialization with address constants.

A static-storage object may be initialized with the address of a function or
of an externally-linked object (these are link-time relocations, not runtime
code). This exercises function pointers in static structs (positional and
designated), an ops-style vtable, an array of function pointers, and a static
pointer to an external array.
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


class TestStaticAddressConstants(unittest.TestCase):
    def test_function_pointer_positional(self):
        self.assertEqual(_run(
            "int f(void){return 42;} struct O{int(*fn)(void);};"
            "static struct O o={f}; int main(){return o.fn();}"), 42)

    def test_function_pointer_designated(self):
        self.assertEqual(_run(
            "int f(void){return 42;} struct O{int(*fn)(void);};"
            "static struct O o={.fn=f}; int main(){return o.fn();}"), 42)

    def test_static_function_pointer(self):
        self.assertEqual(_run(
            "static int sf(void){return 42;} struct O{int(*fn)(void);};"
            "static struct O o={.fn=sf}; int main(){return o.fn();}"), 42)

    def test_ops_vtable(self):
        self.assertEqual(_run(
            "int a(void){return 10;} int b(int x){return x;}"
            "struct Ops{int(*f1)(void);int(*f2)(int);int pad;};"
            "static const struct Ops ops={.f1=a,.f2=b,.pad=5};"
            "int main(){return ops.f1()+ops.f2(20)+ops.pad*0+12;}"), 42)

    def test_array_of_function_pointers(self):
        self.assertEqual(_run(
            "int x(void){return 1;} int y(void){return 41;}"
            "static int(*tab[2])(void)={x,y};"
            "int main(){return tab[0]()+tab[1]();}"), 42)

    def test_pointer_to_external_array(self):
        self.assertEqual(_run(
            "int arr[3]={1,2,3}; static int*p=arr;"
            "int main(){return p[0]+p[1]+p[2];}"), 6)

    def test_plain_static_init_unaffected(self):
        self.assertEqual(_run(
            "static int t[3]={7,14,21}; int main(){return t[0]+t[1]+t[2];}"),
            42)


if __name__ == "__main__":
    unittest.main()


class TestStaticInternalAddr(unittest.TestCase):
    """Address of a file-scope `static` (internal-linkage) object is a valid
    address constant in a static initializer; the label is consistent between
    the definition and the reference."""

    def _run(self, src):
        import os, subprocess, tempfile
        d = tempfile.mkdtemp()
        c = os.path.join(d, "t.c")
        with open(c, "w") as f:
            f.write(src)
        out = os.path.join(d, "t")
        p = subprocess.run(["shivyc", c, "-o", out], capture_output=True,
                           text=True)
        if p.returncode != 0:
            return None, p.stdout + p.stderr
        return subprocess.run([out]).returncode, ""

    def test_addr_of_internal_static(self):
        rc, err = self._run("static int backing = 7;\n"
                            "static int *p = &backing;\n"
                            "int main(void){ return *p; }\n")
        self.assertEqual(rc, 7, err)

    def test_addr_of_static_struct_in_aggregate(self):
        rc, err = self._run("typedef struct { int x; } N;\n"
                            "static N nm = { 42 };\n"
                            "struct T { N *np; };\n"
                            "struct T t = { &nm };\n"
                            "int main(void){ return t.np->x; }\n")
        self.assertEqual(rc, 42, err)

    def test_distinct_statics_distinct_labels(self):
        rc, err = self._run("static int a=1; static int b=2;\n"
                            "static int *pa=&a; static int *pb=&b;\n"
                            "int main(void){ return *pa*10 + *pb; }\n")
        self.assertEqual(rc, 12, err)
