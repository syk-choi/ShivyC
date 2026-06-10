"""C11 anonymous struct/union members: inner members are accessible directly
on the enclosing struct/union, at the correct offsets."""
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


class TestAnonMembers(unittest.TestCase):
    def test_anon_union_with_anon_struct(self):
        # Mirrors CPython's PyObject: anon union holding an anon struct.
        rc, err = _run(
            "struct obj {\n"
            "  union { long full; struct {\n"
            "    unsigned int refcnt; unsigned short overflow;\n"
            "    unsigned short flags; }; };\n"
            "  void *type;\n"
            "};\n"
            "int main(void){\n"
            "  struct obj o; o.full = 0;\n"
            "  o.refcnt = 0x11111111u; o.flags = 0x3333;\n"
            "  if ((unsigned int)o.full != 0x11111111u) return 1;\n"
            "  if (sizeof(struct obj) != 16) return 2;\n"
            "  return (int)o.refcnt - 0x11111110;\n"   # 1
            "}\n")
        self.assertEqual(rc, 1, err)

    def test_anon_struct_in_struct(self):
        rc, err = _run(
            "struct s { int a; struct { int b; int c; }; int d; };\n"
            "int main(void){\n"
            "  struct s x; x.a=1; x.b=2; x.c=3; x.d=4;\n"
            "  return x.a + x.b + x.c + x.d;\n"   # 10
            "}\n")
        self.assertEqual(rc, 10, err)
