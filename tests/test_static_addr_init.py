"""A parenthesized address-of-static (e.g. (&Obj), as produced by macros like
CPython's PyObject_HEAD_INIT) is a valid address constant inside a static
aggregate initializer."""
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


class TestStaticAddrInit(unittest.TestCase):
    def test_paren_addr_in_aggregate(self):
        rc, err = _run(
            "struct T { int magic; };\n"
            "struct T Obj = { 42 };\n"
            "struct S { struct T *p; int v; };\n"
            "struct S s = { (&Obj), 7 };\n"   # parenthesized address constant
            "int main(void){ return s.p->magic + s.v; }\n")  # 49
        self.assertEqual(rc, 49, err)

    def test_nested_aggregate_paren_addr(self):
        rc, err = _run(
            "struct T { int magic; };\n"
            "struct T Obj = { 5 };\n"
            "struct Inner { long full; struct T *p; };\n"
            "struct Outer { struct Inner i; };\n"
            "struct Outer o = { { 99, (&Obj) } };\n"
            "int main(void){ return o.i.p->magic + (int)o.i.full; }\n")  # 104
        self.assertEqual(rc, 104, err)

    def test_func_ptr_cast_scalar(self):
        # A function address cast to a function-pointer type is an address
        # constant (as in CPython's clinic-generated method tables).
        rc, err = _run(
            "int myfunc(void){ return 7; }\n"
            "typedef int (*FP)(void);\n"
            "static FP g = (FP)myfunc;\n"
            "int main(void){ return g(); }\n")
        self.assertEqual(rc, 7, err)

    def test_func_ptr_cast_in_method_table(self):
        # Mirrors a PyMethodDef[] table: {name, (PyCFunction)fn, flags, doc}.
        rc, err = _run(
            "typedef int (*PyCFunction)(void);\n"
            "static int len_hint(void){ return 11; }\n"
            "static int reduce(void){ return 31; }\n"
            "struct M { char *name; PyCFunction f; int flags; };\n"
            "static struct M methods[] = {\n"
            '  {"__length_hint__", (PyCFunction)len_hint, 4},\n'
            '  {"__reduce__", (PyCFunction)reduce, 4},\n'
            "};\n"
            "int main(void){ return methods[0].f() + methods[1].f(); }\n")
        self.assertEqual(rc, 42, err)


    def test_pointer_arithmetic_address_constant(self):
        # `ARRAY + n` as a static initializer is a link-time symbol+offset
        # (musl's ctype tables: `static const int32_t *const p = table+128;`).
        rc, err = _run(
            "static const int t[200] = {[128]=77,[130]=99};\n"
            "static const int *const p = t + 128;\n"
            "int main(void){ return p[0] + p[2]; }\n")  # 77+99=176
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 176)


class TestMemberAddrStaticInit(unittest.TestCase):
    """&OBJ.member... as a static address constant (symbol + offset)."""

    def _run(self, src):
        import os, subprocess, tempfile
        d = tempfile.mkdtemp()
        c = os.path.join(d, "t.c"); out = os.path.join(d, "t")
        with open(c, "w") as f:
            f.write(src)
        p = subprocess.run(["shivyc", "--no-cache", c, "-o", out],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return subprocess.run([out]).returncode

    def test_nested_member_address(self):
        rc = self._run(
            "struct Inner { long a; long b; };\n"
            "struct Outer { long x; struct Inner in; };\n"
            "static struct Outer g = { 10, { 20, 30 } };\n"
            "static long *p = &g.in.b;\n"
            "static long *arr[2] = { &g.in.a, &g.in.b };\n"
            "int main(){ return (int)(*p + *arr[0] + *arr[1]); }\n")  # 30+20+30
        self.assertEqual(rc, 80)

    def test_array_member_decay_self(self):
        # A bare array-member access decays to its address (no &): an address
        # constant. Mirrors CPython _PyRuntime fields initialized with an array
        # member of the object being defined.
        rc, err = _run(
            "struct inner { int arr[4]; int scalar; };\n"
            "struct outer { struct inner in; int *parr; };\n"
            "extern struct outer G;\n"
            "struct outer G = { .in = { .arr = {10,20,30,40}, .scalar = 99 },\n"
            "                   .parr = G.in.arr };\n"
            "int main(void){ return (G.parr == &G.in.arr[0]\n"
            "                        && G.parr[2] == 30) ? 17 : 0; }\n")  # 17
        self.assertEqual(rc, 17, err)

    def test_addr_then_arrow_member(self):
        # (&E)->m.arr  ==  E.m.arr  : the -> dereferences the address from &E.
        # Mirrors CPython _PyRuntime's `&(_PyRuntime.x.y.z)` re-accessed via ->.
        rc, err = _run(
            "struct leaf { int data[3]; };\n"
            "struct mid  { struct leaf lf; };\n"
            "struct top  { struct mid md; int *p; void *q; };\n"
            "extern struct top G;\n"
            "struct top G = { .md = { .lf = { .data = {7,8,9} } },\n"
            "                 .p = (&(G.md))->lf.data,\n"
            "                 .q = &((&(G.md))->lf) };\n"
            "int main(void){ return ((G.p == &G.md.lf.data[0])\n"
            "                        && (G.p[1] == 8)\n"
            "                        && (G.q == &G.md.lf)) ? 19 : 0; }\n")  # 19
        self.assertEqual(rc, 19, err)
