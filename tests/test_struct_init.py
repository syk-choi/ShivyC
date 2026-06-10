"""Struct/union copy-initialization of a local from a struct-valued expression.

A struct local may be initialized from a compound literal or from another
struct value (copy-initialization), not only from a brace initializer list.
These are lowered exactly like struct assignment.
"""
import os
import subprocess
import tempfile
import unittest


def _run(src):
    d = tempfile.mkdtemp()
    c = os.path.join(d, "t.c")
    out = os.path.join(d, "t")
    with open(c, "w") as f:
        f.write(src)
    p = subprocess.run(["shivyc", "--no-cache", c, "-o", out],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None, p.stdout + p.stderr
    return subprocess.run([out]).returncode, ""


class TestStructInit(unittest.TestCase):
    def test_compound_literal_init(self):
        rc, err = _run(
            "struct S { long bits; int tag; };\n"
            "int main(){ struct S c = (struct S){ .bits = 9, .tag = 3 };\n"
            "  return (int)(c.bits + c.tag); }\n")  # 12
        self.assertEqual(rc, 12, err)

    def test_copy_from_other_struct(self):
        rc, err = _run(
            "struct S { long bits; int tag; };\n"
            "int main(){ struct S a; a.bits = 5; a.tag = 7;\n"
            "  struct S b = a;\n"
            "  return (int)(b.bits + b.tag); }\n")  # 12
        self.assertEqual(rc, 12, err)

    def test_union_copy_init(self):
        rc, err = _run(
            "union U { long l; int i; };\n"
            "int main(){ union U a; a.l = 41;\n"
            "  union U b = a;\n"
            "  return (int)b.l + 1; }\n")  # 42
        self.assertEqual(rc, 42, err)


if __name__ == "__main__":
    unittest.main()
