"""Language-feature fixes surfaced while compiling CPython's longobject.c:

- C11 `static_assert` / `_Static_assert` (accepted and ignored),
- constant folding of `!` so it can appear in constant contexts such as
  array sizes (CPython's Py_BUILD_ASSERT_EXPR uses `sizeof(char[1-2*!(c)])`),
- a null pointer constant converting to a function pointer.
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


class TestStaticAssert(unittest.TestCase):
    def test_file_and_block_scope(self):
        rc, err = _run(
            "_Static_assert(sizeof(long) == 8, \"file scope\");\n"
            "static_assert(1, \"also file scope\");\n"
            "int f(void){ static_assert(1+1 == 2, \"block\"); return 7; }\n"
            "int main(){ return f(); }\n")
        self.assertEqual(rc, 7, err)


class TestBoolNotFolding(unittest.TestCase):
    def test_not_in_array_size(self):
        # Py_BUILD_ASSERT_EXPR-style array trick must fold to a constant.
        rc, err = _run(
            "int main(){\n"
            "  int r = (int)(sizeof(char [1 - 2*!(1 == 1)]) - 1);\n"
            "  return r + 42; }\n")  # array size 1, r == 0
        self.assertEqual(rc, 42, err)

    def test_not_folding_values(self):
        rc, err = _run(
            "int a[!0 + !!5];\n"   # !0=1, !!5=1 -> size 2
            "int main(){ return (int)(sizeof(a)/sizeof(int)); }\n")  # 2
        self.assertEqual(rc, 2, err)


class TestNullToFunctionPointer(unittest.TestCase):
    def test_null_constant_to_fptr(self):
        rc, err = _run(
            "typedef int (*fp)(int);\n"
            "int main(){ fp g = (void*)0; fp h = 0;\n"
            "  return (g == 0 && h == 0) ? 55 : 1; }\n")
        self.assertEqual(rc, 55, err)


if __name__ == "__main__":
    unittest.main()


class TestLargeFunctionAllocates(unittest.TestCase):
    """A large single function must compile and run correctly (guards the
    register-allocator coalesce/freeze paths that were formerly super-linear).
    """

    def test_big_function(self):
        lines = ["int big(int x){", "  int a=x;"]
        for i in range(150):
            lines.append(f"  a = a*3 + {i} - (a>>1) + ({i}^a);")
        lines.append("  return a & 0x7f; }")
        lines.append("int main(){ return big(1); }")
        src = "\n".join(lines)
        rc, err = _run(src)
        self.assertIsNotNone(rc, err)
        # Reference value computed the same way.
        a = 1
        for i in range(150):
            a = (a * 3 + i - (a >> 1) + (i ^ a)) & 0xFFFFFFFF
            if a >= 2**31:
                a -= 2**32
        self.assertEqual(rc, a & 0x7f)
