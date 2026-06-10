"""A parameter whose name matches a typedef must not leak out of the
parameter list and shadow that typedef in the enclosing scope."""
import os
import subprocess
import tempfile
import unittest


def _ok(src):
    d = tempfile.mkdtemp()
    c = os.path.join(d, "t.c")
    with open(c, "w") as f:
        f.write(src)
    out = os.path.join(d, "t")
    p = subprocess.run(["shivyc", c, "-o", out], capture_output=True,
                       text=True)
    return p.returncode == 0, p.stdout + p.stderr, out


class TestParamScope(unittest.TestCase):
    def test_param_named_like_typedef_does_not_leak(self):
        ok, err, _ = _ok(
            "typedef void (*destructor)(int);\n"
            "void setit(int x, int destructor);\n"      # param name == typedef
            "void use(const destructor d){ (void)d; }\n"  # still a type here
            "int main(void){ return 0; }\n")
        self.assertTrue(ok, err)

    def test_definition_params_still_usable(self):
        ok, err, exe = _ok(
            "typedef int T;\n"
            "int add(T a, T b){ return a + b; }\n"
            "int main(void){ return add(40, 2); }\n")
        self.assertTrue(ok, err)
        self.assertEqual(subprocess.run([exe]).returncode, 42)

    def test_param_shadows_typedef_in_body(self):
        # A parameter named like a file-scope typedef must be usable as a
        # value inside the body (CPython names a parameter `string` while
        # `typedef PyObject *string;` exists at file scope).
        ok, err, exe = _ok(
            "typedef long *string;\n"
            "typedef struct S { int v; } S;\n"
            "static int impl(S *t, long *s){ return t->v + (int)*s; }\n"
            "static int wrap(void *type, long *string){\n"
            "  return impl((S *)type, string);\n"
            "}\n"
            "int main(void){ S s; s.v = 40; long n = 2;\n"
            "  return wrap(&s, &n); }\n")
        self.assertTrue(ok, err)
        self.assertEqual(subprocess.run([exe]).returncode, 42)
