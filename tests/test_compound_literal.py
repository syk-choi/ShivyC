"""C99 compound literals: ( type-name ) { initializer-list }."""

import os
import subprocess
import tempfile
import unittest


def _run(src):
    d = tempfile.mkdtemp()
    c = os.path.join(d, "t.c")
    with open(c, "w") as f:
        f.write(src)
    out = os.path.join(d, "t")
    if subprocess.run(["shivyc", c, "-o", out],
                      capture_output=True, text=True).returncode != 0:
        return None
    return subprocess.run([out]).returncode


class TestCompoundLiteral(unittest.TestCase):
    def test_scalar(self):
        self.assertEqual(_run("int main(){ return (int){42}; }"), 42)

    def test_struct(self):
        self.assertEqual(
            _run("struct P{int x;int y;};"
                 "int main(){ return ((struct P){3,4}).y; }"), 4)

    def test_struct_designated_trailing_comma(self):
        self.assertEqual(
            _run("struct P{int a;int b;};"
                 "int main(){ return ((struct P){.a=5,.b=7,}).a; }"), 5)

    def test_array(self):
        self.assertEqual(
            _run("int main(){ int *p=(int[]){10,20,30}; return p[1]; }"), 20)

    def test_union_punning_double_to_bits(self):
        # The musl asuint64 idiom.
        self.assertEqual(
            _run("typedef unsigned long u64;"
                 "u64 bits(double f){"
                 " return ((union{double _f; u64 _i;}){f})._i; }"
                 "int main(){ return bits(0.0)==0; }"), 1)

    def test_union_punning_bits_to_double(self):
        # The musl asdouble idiom; 0x4008000000000000 == 3.0.
        self.assertEqual(
            _run("typedef unsigned long u64;"
                 "double fr(u64 i){"
                 " return ((union{u64 _i; double _f;}){i})._f; }"
                 "int main(){ return (int)fr(0x4008000000000000); }"), 3)

    def test_cast_still_parses(self):
        # A parenthesized type-name NOT followed by '{' is still a cast.
        self.assertEqual(_run("int main(){ double x=3.9; return (int)x; }"), 3)
