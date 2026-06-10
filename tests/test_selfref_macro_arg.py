"""A self-referential function-like macro (blue-painted in its own expansion)
used inside another macro's argument must keep its blue paint. Regression for a
hide-set bug where _subst/_gather_args stripped hide sets, so an already-
expanded self-referential call inside a reused argument was wrongly re-expanded,
corrupting hide sets and leaving sibling macros (e.g. CPython's _PyObject_CAST)
unexpanded. Mirrors `Py_VISIT(PyCFunction_GET_CLASS(m))`."""
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
    p = subprocess.run(["shivyc", c, "-o", out], capture_output=True, text=True)
    if p.returncode != 0:
        return None, p.stdout + p.stderr
    return subprocess.run([out]).returncode, ""


class TestSelfRefMacroArg(unittest.TestCase):
    def test_selfref_in_outer_arg(self):
        # CLS is a self-referential macro wrapping an inline fn of the same
        # name; VISIT (the outer) also uses _PyObject_CAST in its body.
        rc, err = _run(
            "#define _Py_CAST(t,e) ((t)(e))\n"
            "#define _PyObject_CAST(op) _Py_CAST(int,(op))\n"
            "static inline int CLS(int x){ return x; }\n"
            "#define CLS(func) CLS(_PyObject_CAST(func))\n"
            "#define VISIT(op) ((_PyObject_CAST(op)) + 0)\n"
            "int main(void){ return VISIT(CLS(5)); }\n")
        self.assertEqual(rc, 5, err)

    def test_selfref_direct_and_nested(self):
        rc, err = _run(
            "#define _Py_CAST(t,e) ((t)(e))\n"
            "#define _PyObject_CAST(op) _Py_CAST(int, (op))\n"
            "static inline int G(int x){ return x; }\n"
            "#define G(func) G(_PyObject_CAST(func))\n"
            "int main(void){ return G(5) + G(G(0)); }\n")  # 5 + 0
        self.assertEqual(rc, 5, err)
