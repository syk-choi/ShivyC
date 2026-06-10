"""A char array initialized by a string literal copies the bytes into the
array's storage (both static and automatic), inferring size when needed and
zero-padding a larger array."""
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


class TestStringArrayInit(unittest.TestCase):
    def test_static_char_array(self):
        rc, err = _run('static const char d[] = "hi";\n'
                       'int main(void){ return d[0] + d[1]; }\n')  # 209
        self.assertEqual(rc, 209, err)

    def test_auto_char_array(self):
        rc, err = _run('int main(void){ char d[] = "hi";'
                       ' return d[0] + d[1]; }\n')  # 209
        self.assertEqual(rc, 209, err)

    def test_sized_array_zero_pads(self):
        rc, err = _run('char g[10] = "AB";\n'
                       'int main(void){ return g[0]+g[1]+g[2]+g[9]; }\n')  # 131
        self.assertEqual(rc, 131, err)
