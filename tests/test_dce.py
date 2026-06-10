"""Dead-function elimination of unreachable static helpers (-O4, multi-TU).

After whole-program inlining a `static` helper often has no remaining callers;
it is then dropped. Only internal-linkage functions are removed, and only when
provably unreachable from every root (external functions, address-taken
functions, static-initializer references, and inline-asm references). These
drive the real multi-file CLI, run the binary, and check both the result and
whether the function's definition survived.
"""

import os
import re
import subprocess
import tempfile
import unittest


def _write(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write(text)
    return p


def _build(lib_src, main_src):
    """Compile main.c + lib.c at -O4; return (rc, exit_code, main_asm)."""
    d = tempfile.mkdtemp()
    lib = _write(d, "lib.c", lib_src)
    mn = _write(d, "main.c", main_src)
    out = os.path.join(d, "prog")
    env = dict(os.environ, SHIVYC_CACHE_DIR=os.path.join(d, "cache"))
    rc = subprocess.run(["shivyc", "-O4", mn, lib, "-o", out],
                        env=env, capture_output=True, text=True).returncode
    code = subprocess.run([out]).returncode if rc == 0 else None
    s = os.path.splitext(mn)[0] + ".s"
    asm = ""
    if os.path.exists(s):
        with open(s) as f:
            asm = f.read()
    return rc, code, asm


def _defines(asm, fn):
    """Whether the asm still defines a label for function `fn`."""
    return re.search(r"(?m)^" + re.escape(fn) + r"(\.\d+)?:", asm) is not None


class TestDeadFunctionElimination(unittest.TestCase):
    def test_inlined_static_helper_eliminated(self):
        rc, code, asm = _build(
            "int compute(int);",
            "static int dbl(int x){ return x+x; }"
            "int compute(int n){ return dbl(n)+dbl(n+1); }"
            "int main(){ return compute(10); }")            # 20+22
        self.assertEqual((rc, code), (0, 42))
        self.assertFalse(_defines(asm, "dbl"))              # gone

    def test_branchy_static_helper_eliminated(self):
        rc, code, asm = _build(
            "int run(int);",
            "static int clamp(int x){ if(x<0) return 0; return x; }"
            "int run(int n){ return clamp(n)+clamp(-n); }"
            "int main(){ return run(42); }")
        self.assertEqual((rc, code), (0, 42))
        self.assertFalse(_defines(asm, "clamp"))

    def test_transitive_dead_chain(self):
        # deep (a leaf) is inlined into mid and then dead; mid stays (it is not
        # a leaf, so it is a real call from top).
        rc, code, asm = _build(
            "int top(int);",
            "static int deep(int x){ return x+1; }"
            "static int mid(int x){ return deep(x)+deep(x); }"
            "int top(int x){ return mid(x); }"
            "int main(){ return top(20); }")                # (21)*2
        self.assertEqual((rc, code), (0, 42))
        self.assertFalse(_defines(asm, "deep"))             # eliminated
        self.assertTrue(_defines(asm, "mid"))               # still live

    def test_address_taken_static_kept(self):
        # dbl's address is taken, so it may be called indirectly: keep it.
        rc, code, asm = _build(
            "int c(int);",
            "static int dbl(int x){ return x+x; }"
            "int c(int n){ int(*f)(int)=dbl; return f(n)+dbl(n); }"
            "int main(){ return c(10); }")                  # 20+20
        self.assertEqual((rc, code), (0, 40))
        self.assertTrue(_defines(asm, "dbl"))               # kept

    def test_static_init_pointer_table_kept(self):
        # Statics reachable only through a function-pointer table (a static
        # initializer) must be kept -- the reference bypasses IL call/AddrOf.
        rc, code, asm = _build(
            "int run(int);",
            "static int ha(int x){ return x+100; }"
            "static int hb(int x){ return x+200; }"
            "static int (*table[2])(int) = { ha, hb };"
            "int run(int i){ return table[i](5); }"
            "int main(){ return run(1) - 163; }")           # 205-163
        self.assertEqual((rc, code), (0, 42))
        self.assertTrue(_defines(asm, "ha"))
        self.assertTrue(_defines(asm, "hb"))

    def test_external_function_kept(self):
        # An external function with no caller in this program is still kept:
        # another unit could call it. (It is not inlinable here -- it has a
        # call -- so it simply remains defined.)
        rc, code, asm = _build(
            "int helper(int);",
            "int unused_api(int x){ return x*3; }"
            "int main(){ return 42; }")
        self.assertEqual((rc, code), (0, 42))
        self.assertTrue(_defines(asm, "unused_api"))        # external: kept


if __name__ == "__main__":
    unittest.main()
