"""C99 __func__ (and the GCC aliases) resolve to the enclosing function name."""
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


class TestFuncMacro(unittest.TestCase):
    def test_func_is_function_name(self):
        # strcmp(__func__, "check") == 0, and __func__[0] == 'm' (109)
        rc, err = _run(
            "extern int strcmp(const char*, const char*);\n"
            "int myfunc(void){ return __func__[0]; }\n"
            "int check(void){ return strcmp(__func__, \"check\"); }\n"
            "int main(void){ return myfunc() + check(); }\n")
        self.assertEqual(rc, 109, err)

    def test_function_alias(self):
        rc, err = _run(
            "extern int strcmp(const char*, const char*);\n"
            "int here(void){ return strcmp(__FUNCTION__, \"here\"); }\n"
            "int main(void){ return here(); }\n")
        self.assertEqual(rc, 0, err)
