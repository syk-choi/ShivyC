"""Passing structs by value as function arguments (SysV AMD64).

A struct of 9..16 bytes (INTEGER class) is passed in two consecutive integer
registers; a larger struct is passed on the stack. These tests check the value
against gcc for register- and stack-passed structs, including structs mixed
with scalar arguments and combined with a struct return.
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


class TestStructArgs(unittest.TestCase):
    def _matches_gcc(self, src):
        ref = _gcc_run(src)
        if ref is None:
            self.skipTest("gcc unavailable")
        self.assertEqual(_shivyc_run(src) & 0xff, ref & 0xff)

    def test_arg_16_two_regs(self):
        self._matches_gcc(
            "struct Q { long a, b; };\n"
            "long use(struct Q q){ return q.a + q.b; }\n"
            "int main(){ struct Q q; q.a=10; q.b=20;"
            " return (int)use(q); }\n")  # 30

    def test_arg_mixed_with_scalars(self):
        self._matches_gcc(
            "struct Q { long a, b; };\n"
            "long use(int x, struct Q q, int y){ return x+q.a+q.b+y; }\n"
            "int main(){ struct Q q; q.a=10; q.b=20;"
            " return (int)use(1, q, 2); }\n")  # 33

    def test_arg_24_on_stack(self):
        self._matches_gcc(
            "struct B { long a,b,c; };\n"
            "long use(struct B b){ return b.a+b.b+b.c; }\n"
            "int main(){ struct B b; b.a=10;b.b=20;b.c=30;"
            " return (int)use(b); }\n")  # 60

    def test_arg_and_return_struct(self):
        self._matches_gcc(
            "struct Q { long a, b; };\n"
            "struct Q swap(struct Q q){ struct Q r; r.a=q.b; r.b=q.a;"
            " return r; }\n"
            "int main(){ struct Q q={10,20}; struct Q r=swap(q);"
            " return (int)(r.a + r.b*10); }\n")  # 20 + 100 = 120

    def test_arg_12_three_ints(self):
        self._matches_gcc(
            "struct T { int a,b,c; };\n"
            "int use(struct T t){ return t.a+t.b+t.c; }\n"
            "int main(){ struct T t; t.a=3;t.b=4;t.c=5;"
            " return use(t); }\n")  # 12


if __name__ == "__main__":
    unittest.main()
