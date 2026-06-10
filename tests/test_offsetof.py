"""__builtin_offsetof yields the byte offset of a member, matching where the
compiler actually places that member (self-consistent), including nested
members and array subscripts."""
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
    p = subprocess.run(["shivyc", c, "-o", out], capture_output=True,
                       text=True)
    if p.returncode != 0:
        return None, p.stdout + p.stderr
    return subprocess.run([out]).returncode, ""


class TestOffsetof(unittest.TestCase):
    def test_self_consistent(self):
        # offsetof must equal the actual member address minus the base.
        rc, err = _run(
            "struct S { char c; int x; struct {int a;int b;} in; int arr[5]; };\n"
            "int main(void){\n"
            "  struct S s; char *base = (char*)&s; int ok = 1;\n"
            "  if ((char*)&s.c - base != (long)__builtin_offsetof(struct S, c)) ok=0;\n"
            "  if ((char*)&s.x - base != (long)__builtin_offsetof(struct S, x)) ok=0;\n"
            "  if ((char*)&s.in.b - base != (long)__builtin_offsetof(struct S, in.b)) ok=0;\n"
            "  if ((char*)&s.arr[3] - base != (long)__builtin_offsetof(struct S, arr[3])) ok=0;\n"
            "  return ok;\n"
            "}\n")
        self.assertEqual(rc, 1, err)

    def test_first_member_is_zero(self):
        rc, err = _run(
            "struct S { int first; int second; };\n"
            "int main(void){ return (int)__builtin_offsetof(struct S, first); }\n")
        self.assertEqual(rc, 0, err)

    def test_usable_in_static_init(self):
        # The case CPython needs: offsetof in a static initializer.
        rc, err = _run(
            "struct S { long a; int b[1]; };\n"
            "unsigned long basic = __builtin_offsetof(struct S, b);\n"
            "int main(void){ return (int)basic; }\n")  # 8 (packed: long at 0, b at 8)
        self.assertEqual(rc, 8, err)
