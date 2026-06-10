"""Returning small structs by value (SysV AMD64: 9..16 bytes in RAX:RDX).

A function returning a struct of up to 16 bytes returns it in the RAX:RDX
register pair (the low eightbyte in RAX, the high one in RDX); the caller
stores both halves into the result's memory home. These tests check the value
is correct (vs gcc) for the common sizes and that an 8-byte struct (single
register) still works.
"""
import os
import shutil
import subprocess
import tempfile
import unittest


def _shivyc_run(src):
    d = tempfile.mkdtemp()
    c = os.path.join(d, "t.c")
    out = os.path.join(d, "t")
    with open(c, "w") as f:
        f.write(src)
    p = subprocess.run(["shivyc", "--no-cache", c, "-o", out],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    return subprocess.run([out]).returncode


def _gcc_run(src):
    if not shutil.which("gcc"):
        return None
    d = tempfile.mkdtemp()
    c = os.path.join(d, "t.c")
    out = os.path.join(d, "t")
    with open(c, "w") as f:
        f.write(src)
    if subprocess.run(["gcc", c, "-o", out],
                      capture_output=True).returncode != 0:
        return None
    return subprocess.run([out]).returncode


TWO_LONGS = (
    "struct Q { long a; long b; };\n"
    "struct Q mk(long x, long y){ struct Q q; q.a=x; q.b=y; return q; }\n"
    "int main(){ struct Q r = mk(40,60);\n"
    "  struct Q s = mk(r.a+1, r.b+1);\n"
    "  return (int)((r.a+r.b+s.a+s.b) & 0xff); }\n")        # 202

THREE_INTS = (                                              # 12 bytes, align 4
    "struct T { int a; int b; int c; };\n"
    "struct T mk3(int x){ struct T t; t.a=x; t.b=x*2; t.c=x*3; return t; }\n"
    "int main(){ struct T r = mk3(7); return r.a+r.b+r.c; }\n")   # 42

ONE_LONG = (                                                # 8 bytes (RAX only)
    "struct P { long a; };\n"
    "struct P mk(long x){ struct P p; p.a=x; return p; }\n"
    "int main(){ struct P r = mk(99); return (int)r.a; }\n")      # 99

LONG_AND_INT = (                                            # 16 bytes (padded)
    "struct M { long a; int b; };\n"
    "struct M mk(long x, int y){ struct M m; m.a=x; m.b=y; return m; }\n"
    "int main(){ struct M r = mk(100, 23); return (int)(r.a + r.b); }\n")  # 123


class TestStructReturn(unittest.TestCase):
    def _matches_gcc(self, src):
        ref = _gcc_run(src)
        if ref is None:
            self.skipTest("gcc unavailable")
        self.assertEqual(_shivyc_run(src) & 0xff, ref & 0xff)

    def test_two_longs_16(self):
        self._matches_gcc(TWO_LONGS)

    def test_three_ints_12(self):
        self._matches_gcc(THREE_INTS)

    def test_one_long_8(self):
        self._matches_gcc(ONE_LONG)

    def test_long_and_int_16(self):
        self._matches_gcc(LONG_AND_INT)

    def test_sret_24_three_longs(self):
        self._matches_gcc(
            "struct B { long a, b, c; };\n"
            "struct B mk(long x){ struct B b; b.a=x; b.b=x*2; b.c=x*3;"
            " return b; }\n"
            "int main(){ struct B r = mk(7);\n"
            "  struct B s = mk(r.a + r.b);\n"
            "  return (int)((r.a+r.b+r.c + s.a+s.b+s.c) & 0xff); }\n")  # 168

    def test_sret_with_extra_args(self):
        # Verifies the hidden result pointer takes RDI and real args shift.
        self._matches_gcc(
            "struct B { long a, b, c; };\n"
            "struct B mk(long p, long q, long r){ struct B s;"
            " s.a=p; s.b=q; s.c=r; return s; }\n"
            "int main(){ struct B v = mk(10,20,30);"
            " return (int)(v.a+v.b+v.c); }\n")  # 60

    def test_sret_32(self):
        self._matches_gcc(
            "struct C { long a,b,c,d; };\n"
            "struct C mk(long x){ struct C c; c.a=x;c.b=x+1;c.c=x+2;c.d=x+3;"
            " return c; }\n"
            "int main(){ struct C r=mk(10);"
            " return (int)(r.a+r.b+r.c+r.d); }\n")  # 46

    def test_large_struct_assignment(self):
        # The >16-byte copy path (move_data with 3+ chunks) is also exercised
        # by plain struct assignment, independent of any call.
        self._matches_gcc(
            "struct C { long a,b,c,d; };\n"
            "int main(){ struct C x; x.a=1;x.b=2;x.c=3;x.d=4;"
            " struct C y; y=x; return (int)(y.a+y.b+y.c+y.d); }\n")  # 10


if __name__ == "__main__":
    unittest.main()
