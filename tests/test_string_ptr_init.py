"""A string literal initializing a pointer (scalar, aggregate member, or array
element) with static storage emits the bytes and points the pointer at them."""
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


class TestStringPtrInit(unittest.TestCase):
    def test_scalar_pointer(self):
        rc, err = _run('static const char *p = "hi";\n'
                       'int main(void){ return p[0] + p[1]; }\n')  # 209
        self.assertEqual(rc, 209, err)

    def test_pointer_in_aggregate(self):
        rc, err = _run('struct T { const char *name; int sz; };\n'
                       'struct T t = { "bool", 5 };\n'
                       'int main(void){ return t.name[0] + t.sz; }\n')  # 103
        self.assertEqual(rc, 103, err)

    def test_array_of_string_pointers(self):
        rc, err = _run('const char *msgs[] = {"ab", "cd"};\n'
                       'int main(void){ return msgs[0][0] + msgs[1][1]; }\n')  # 197
        self.assertEqual(rc, 197, err)
