"""Cross-translation-unit soundness of the whole-program safety analyses.

The metamorphic-reentrancy check (a metamorphic function uses one static return
slot, so it must not be re-entrant) and the -O4 near-scratch check (a function
may keep its locals in a static buffer only if it cannot be active twice at
once) reason about the call graph. Compiled per file they only saw one TU and
would miss recursion that travels through another unit. With the whole-program
graph wired in, both now see the entire program.

These are integration tests: they drive the real `shivyc` CLI over multiple
files (the .s files ShivyC writes next to each source are read back to inspect
code generation).
"""

import os
import subprocess
import tempfile
import unittest


def _write(d, name, text):
    path = os.path.join(d, name)
    with open(path, "w") as f:
        f.write(text)
    return path


def _compile(files, out, extra=()):
    """Run shivyc over `files`; return (returncode, output)."""
    env = dict(os.environ, SHIVYC_CACHE_DIR=os.path.join(
        os.path.dirname(out), "cache"))
    proc = subprocess.run(
        ["shivyc", *extra, *files, "-o", out],
        env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def _asm_for(c_path):
    s = os.path.splitext(c_path)[0] + ".s"
    if os.path.exists(s):
        with open(s) as f:
            return f.read()
    return ""


class TestMetamorphicCrossTU(unittest.TestCase):
    def test_recursion_through_other_tu_rejected(self):
        d = tempfile.mkdtemp()
        a = _write(d, "a.c",
                   "int g(int x);\n"
                   "int m(int x) __metamorphic__ "
                   "{ if(x<=0) return 0; return g(x-1); }\n"
                   "int main(){ return m(3); }\n")
        b = _write(d, "b.c", "int m(int x);\nint g(int x){ return m(x); }\n")
        rc, err = _compile([a, b], os.path.join(d, "prog"),
                           extra=["-fmetamorphic"])
        self.assertNotEqual(rc, 0)
        self.assertIn("re-entered", err)

    def test_nonrecursive_cross_tu_ok(self):
        d = tempfile.mkdtemp()
        c = _write(d, "c.c",
                   "int h(int x);\n"
                   "int mm(int x) __metamorphic__ { return h(x)+1; }\n"
                   "int main(){ return mm(7); }\n")
        dd = _write(d, "d.c", "int h(int x){ return x*x; }\n")
        out = os.path.join(d, "ok")
        rc, _ = _compile([c, dd], out, extra=["-fmetamorphic"])
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([out]).returncode, 50)

    def test_single_tu_recursion_still_rejected(self):
        d = tempfile.mkdtemp()
        f = _write(d, "r.c",
                   "int fact(int n) __metamorphic__ "
                   "{ return n<=1 ? 1 : n*fact(n-1); }\n"
                   "int main(){ return fact(5); }\n")
        rc, err = _compile([f], os.path.join(d, "p"), extra=["-fmetamorphic"])
        self.assertNotEqual(rc, 0)
        self.assertIn("re-entered", err)


class TestNearScratchCrossTU(unittest.TestCase):
    _WORK = ("int work(int a,int b,int c,int d,int e,int f,int g,int h){\n"
             " int v1=a+b,v2=b+c,v3=c+d,v4=d+e,v5=e+f,v6=f+g,v7=g+h,v8=h+a;\n"
             " int w1=v1*v2,w2=v3*v4,w3=v5*v6,w4=v7*v8;\n"
             " int s=(w1+w2+w3+w4+v1+v2+v3+v4+v5+v6+v7+v8)&255;\n"
             "%s"
             " return s&255;\n}\n")

    def test_eligible_function_uses_scratch(self):
        d = tempfile.mkdtemp()
        src = self._WORK % "" + "int main(){ return work(1,2,3,4,5,6,7,8); }\n"
        f = _write(d, "sp.c", src)
        rc, _ = _compile([f], os.path.join(d, "sp"), extra=["-O4"])
        self.assertEqual(rc, 0)
        self.assertIn("work__scratch", _asm_for(f))

    def test_cross_tu_recursion_disables_scratch(self):
        d = tempfile.mkdtemp()
        r1 = _write(d, "r1.c",
                    "int other(int x);\n"
                    + (self._WORK % " if(a>0) s+=other(a-1);\n")
                    + "int main(){ return work(1,2,3,4,5,6,7,8); }\n")
        r2 = _write(d, "r2.c",
                    "int work(int,int,int,int,int,int,int,int);\n"
                    "int other(int x){ return work(x,1,1,1,1,1,1,1); }\n")
        rc, _ = _compile([r1, r2], os.path.join(d, "prog"), extra=["-O4"])
        self.assertEqual(rc, 0)
        # work is recursive through r2.c, so it must not get a static buffer.
        self.assertNotIn("work__scratch", _asm_for(r1))


class TestNearScratchEnabling(unittest.TestCase):
    """Whole-program analysis grants near-scratch a sound single-TU analysis
    must refuse: a function calling a function defined in another unit cannot
    be proven non-reentrant from one TU alone."""

    _FN = ("int fn(int x){\n"
           " int a=x+1,b=a*2,c=b-3,d=c+a,e=d+b,f=e+c,g=f+d,"
           "h=g+e,i=h+f,j=i+g,k=j+h,l=k+i;\n"
           " int s=helper(x);\n"
           " return (a+b+c+d+e+f+g+h+i+j+k+l+s)&255;\n}\n")

    def test_single_tu_denies_external_call(self):
        d = tempfile.mkdtemp()
        a = _write(d, "a.c", "int helper(int x);\n" + self._FN +
                   "int main(){ return fn(1); }\n")
        # Links will fail (helper undefined), but the .s is still produced.
        _compile([a], os.path.join(d, "solo"), extra=["-O4"])
        self.assertNotIn("fn__scratch", _asm_for(a))

    def test_whole_program_grants_and_is_correct(self):
        d = tempfile.mkdtemp()
        a = _write(d, "a.c", "int helper(int x);\n" + self._FN +
                   "int main(){ return fn(1); }\n")
        b = _write(d, "b.c", "int helper(int x){ return x*7; }\n")
        out = os.path.join(d, "prog")
        rc, _ = _compile([a, b], out, extra=["-O4"])
        self.assertEqual(rc, 0)
        self.assertIn("fn__scratch", _asm_for(a))   # granted whole-program
        # Result must be unchanged by the optimization.
        ref, _ = _compile([a, b], os.path.join(d, "ref"))  # -O0
        self.assertEqual(subprocess.run([out]).returncode,
                         subprocess.run([os.path.join(d, "ref")]).returncode)

    def test_whole_program_denies_when_callee_cycles_back(self):
        # The dual of the granting case: the same external-linkage fn, but now
        # the other unit's helper calls fn back. Whole-program analysis must
        # see the cross-TU cycle fn -> helper -> fn and refuse near-scratch,
        # and the program must still compute the right answer.
        d = tempfile.mkdtemp()
        a = _write(d, "a.c", "int helper(int x);\n"
                   + (self._FN.replace(" int s=helper(x);\n",
                                       " int s=(x>0)?helper(x-1):0;\n"))
                   + "int main(){ return fn(5); }\n")
        b = _write(d, "b.c", "int fn(int x);\n"
                   "int helper(int x){ return fn(x); }\n")
        out = os.path.join(d, "prog")
        rc, _ = _compile([a, b], out, extra=["-O4"])
        self.assertEqual(rc, 0)
        self.assertNotIn("fn__scratch", _asm_for(a))   # reentrant: refused
        ref, _ = _compile([a, b], os.path.join(d, "ref"))  # -O0
        self.assertEqual(subprocess.run([out]).returncode,
                         subprocess.run([os.path.join(d, "ref")]).returncode)

    def test_static_linkage_eligible_despite_external_call(self):
        d = tempfile.mkdtemp()
        # Both functions call a declared-only external; only linkage differs.
        src = ("int ext(int x);\n"
               "static int sfn(int x){\n"
               " int a=x+1,b=a*2,c=b-3,d=c+a,e=d+b,f=e+c,g=f+d,"
               "h=g+e,i=h+f,j=i+g,k=j+h,l=k+i;\n"
               " return (a+b+c+d+e+f+g+h+i+j+k+l+ext(x))&255;\n}\n"
               "int efn(int x){\n"
               " int a=x+1,b=a*2,c=b-3,d=c+a,e=d+b,f=e+c,g=f+d,"
               "h=g+e,i=h+f,j=i+g,k=j+h,l=k+i;\n"
               " return (a+b+c+d+e+f+g+h+i+j+k+l+ext(x))&255;\n}\n"
               "int main(){ return sfn(1)+efn(2); }\n")
        s = _write(d, "s.c", src)
        _compile([s], os.path.join(d, "s"), extra=["-O4"])
        asm = _asm_for(s)
        self.assertIn("sfn__scratch", asm)      # static: cannot be re-entered
        self.assertNotIn("efn__scratch", asm)   # external linkage: conservative


if __name__ == "__main__":
    unittest.main()
