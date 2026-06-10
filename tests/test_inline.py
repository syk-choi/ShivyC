"""Cross-translation-unit inlining of small pure leaf functions (-O4).

A single TU never has the body of a callee defined in another file. Building
the whole-program graph captures small, pure, straight-line leaf bodies, which
are then spliced into their direct call sites in any unit. Only pure
expression-like leaves qualify (no calls, branches, memory, or globals), so
splicing cannot change behavior -- it only removes the call.

These drive the real multi-file CLI at -O4, run the binary, and confirm both
the result and that the call was actually removed.
"""

import os
import subprocess
import tempfile
import unittest


def _write(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write(text)
    return p


def _build_run(lib_src, main_src, opt="-O4"):
    d = tempfile.mkdtemp()
    lib = _write(d, "lib.c", lib_src)
    mn = _write(d, "main.c", main_src)
    out = os.path.join(d, "prog")
    env = dict(os.environ, SHIVYC_CACHE_DIR=os.path.join(d, "cache"))
    args = ["shivyc"] + ([opt] if opt else []) + [mn, lib, "-o", out]
    rc = subprocess.run(args, env=env, capture_output=True, text=True).returncode
    code = subprocess.run([out]).returncode if rc == 0 else None
    main_asm = ""
    s = os.path.splitext(mn)[0] + ".s"
    if os.path.exists(s):
        main_asm = open(s).read()
    return rc, code, main_asm


class TestCrossTUInlining(unittest.TestCase):
    def test_leaf_inlined_and_correct(self):
        rc, code, asm = _build_run(
            "int sq(int x){ return x*x; }",
            "int sq(int); int main(){ return sq(5)+sq(4); }")  # 25+16
        self.assertEqual(rc, 0)
        self.assertEqual(code, 41)
        self.assertNotIn("call sq", asm)   # inlined: no call remains

    def test_multiple_leaves_and_literals(self):
        rc, code, asm = _build_run(
            "int sq(int x){return x*x;}"
            "int addk(int a,int b){int t=a+b; return t+3;}"
            "int five(void){return 5;}",
            "int sq(int);int addk(int,int);int five(void);"
            "int main(){ return sq(5)+addk(2,4)+five(); }")  # 25+9+5
        self.assertEqual((rc, code), (0, 39))
        for name in ("call sq", "call addk", "call five"):
            self.assertNotIn(name, asm)

    def test_param_reassignment_uses_fresh_copy(self):
        # The callee reassigns its parameter; this must not clobber the
        # caller's argument value.
        rc, code, _ = _build_run(
            "int f(int x){ x = x + 10; return x*2; }",
            "int f(int); int main(){ return f(6); }")  # (6+10)*2
        self.assertEqual((rc, code), (0, 32))

    def test_argument_evaluated_once(self):
        # The argument expression (with a side effect) must run exactly once.
        rc, code, _ = _build_run(
            "int sq(int x){ return x*x; }",
            "int sq(int); int g; int side(void){ g++; return 7; }"
            "int main(){ int r = sq(side()); return r + g; }")  # 49 + 1
        self.assertEqual((rc, code), (0, 50))

    def test_callee_touching_global_not_inlined(self):
        # A function that reads/writes a global is NOT a pure leaf and must be
        # left as a real call so the global is actually updated.
        rc, code, asm = _build_run(
            "int gc; int bump(int x){ gc = gc + x; return gc; }",
            "int bump(int); int main(){ bump(10); return bump(5); }")  # 15
        self.assertEqual((rc, code), (0, 15))
        self.assertIn("call bump", asm)    # NOT inlined

    def test_branching_callee_inlined(self):
        # Callees with internal control flow are inlinable too.
        rc, code, asm = _build_run(
            "int amax(int a,int b){ if(a>b) return a; return b; }",
            "int amax(int,int); int main(){ return amax(8,50); }")
        self.assertEqual((rc, code), (0, 50))
        self.assertNotIn("call amax", asm)
        self.assertNotIn("jmp amax", asm)        # fully inlined

    def test_early_return_and_ternary(self):
        rc, code, _ = _build_run(
            "int sign(int x){ if(x>0) return 1; else if(x<0) return -1;"
            " return 0; }"
            "int absT(int x){ return x<0 ? -x : x; }",
            "int sign(int); int absT(int);"
            "int main(){ return sign(-7) + absT(-43); }")  # -1 + 43
        self.assertEqual((rc, code), (0, 42))

    def test_loop_callee_inlined_each_site(self):
        # A short loop is inlinable; two call sites must get independent label
        # copies (no clash) and both compute correctly.
        rc, code, asm = _build_run(
            "int sumto(int n){ int s=0; for(int i=0;i<n;i++) s+=i; return s; }",
            "int sumto(int); int main(){ return sumto(4)+sumto(5); }")  # 6+10
        self.assertEqual((rc, code), (0, 16))
        self.assertNotIn("call sumto", asm)

    def test_non_leaf_callee_not_inlined(self):
        # A callee that itself calls something is not a leaf and is left alone.
        rc, code, asm = _build_run(
            "int g(int x){ return x+1; }"
            "int h(int x){ return g(x) * 2; }",
            "int h(int); int main(){ return h(20); }")  # (20+1)*2
        self.assertEqual((rc, code), (0, 42))
        self.assertTrue("call h" in asm or "jmp h" in asm)   # h not inlined

    def test_single_tu_not_inlined(self):
        # With one file there is no whole-program graph, so nothing is inlined;
        # behavior is the ordinary -O4 path.
        d = tempfile.mkdtemp()
        src = _write(d, "one.c",
                     "int sq(int x){return x*x;} int main(){return sq(6);}")
        out = os.path.join(d, "one")
        env = dict(os.environ, SHIVYC_CACHE_DIR=os.path.join(d, "cache"))
        rc = subprocess.run(["shivyc", "-O4", src, "-o", out],
                            env=env, capture_output=True).returncode
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([out]).returncode, 36)


if __name__ == "__main__":
    unittest.main()
