"""Whole-program elimination of never-accessed struct members
(-f-eliminate-unused-members).

Verifies the optimization fires across translation units when safe (shrinking
the struct while preserving behavior) and conservatively bails on any
layout-exposing use.
"""
import os
import subprocess
import tempfile
import unittest


def _compile(files, flag=True, report=False, link=True):
    """Compile the given {name: source} files. Returns (proc, dir)."""
    d = tempfile.mkdtemp()
    paths = []
    for name, src in files.items():
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write(src)
        if name.endswith(".c"):
            paths.append(p)
    args = ["shivyc", "--no-cache"]
    if flag:
        args.append("-f-eliminate-unused-members")
    if report:
        args.append("--print-eliminated-members")
    out = os.path.join(d, "prog")
    args += paths + ["-o", out]
    proc = subprocess.run(args, capture_output=True, text=True, cwd=d)
    return proc, out


HEADER = "struct mystruct { int a; int b; int c; };\n"

A_C = ('#include "test_struct.h"\n'
       "struct mystruct GA;\n"
       "int foo(void){ struct mystruct a; a.a = GA.a; a.c = GA.c;"
       " return a.a + a.c; }\n")

B_C = ('#include "test_struct.h"\n'
       "extern struct mystruct GA;\n"
       "int foo(void);\n"
       "int bar(void){ struct mystruct a; a.a = GA.a; a.c = a.a;"
       " return a.a + a.c; }\n"
       "int main(void){ GA.a = 1; GA.c = 2; return foo() + bar(); }\n")


class TestUnusedMemberElim(unittest.TestCase):
    def test_cross_tu_elimination_and_behavior(self):
        # 'b' is never accessed in either TU -> eliminated; a and c still work.
        proc, exe = _compile(
            {"test_struct.h": HEADER, "a.c": A_C, "b.c": B_C}, report=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("eliminated from 'struct mystruct': b", proc.stdout)
        self.assertEqual(subprocess.run([exe]).returncode, 5)

    def test_disabled_by_default(self):
        # Without the flag, nothing is eliminated and behavior is unchanged.
        proc, exe = _compile(
            {"test_struct.h": HEADER, "a.c": A_C, "b.c": B_C},
            flag=False, report=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("eliminated", proc.stdout)
        self.assertEqual(subprocess.run([exe]).returncode, 5)

    def _eliminated(self, body):
        src = ("struct mystruct { int a; int b; int c; };\n" + body)
        proc, _ = _compile({"t.c": src}, report=True)
        return "struct mystruct': b" in proc.stdout, proc

    def test_bails_on_address_taken(self):
        ok, proc = self._eliminated(
            "struct mystruct G;\n"
            "int main(void){ struct mystruct *p = &G; p->a = 1;"
            " return p->a; }\n")
        self.assertFalse(ok, proc.stdout)

    def test_bails_on_sizeof(self):
        ok, _ = self._eliminated(
            "int main(void){ return (int)sizeof(struct mystruct); }\n")
        self.assertFalse(ok)

    def test_bails_on_offsetof(self):
        ok, _ = self._eliminated(
            "int main(void){ return (int)__builtin_offsetof("
            "struct mystruct, c); }\n")
        self.assertFalse(ok)

    def test_bails_on_positional_init(self):
        ok, _ = self._eliminated(
            "struct mystruct G = {1, 2, 3};\n"
            "int main(void){ return G.a; }\n")
        self.assertFalse(ok)

    def test_allows_designated_init(self):
        # Designated initializers name members, so elimination is still safe.
        ok, proc = self._eliminated(
            "struct mystruct G = {.a = 1, .c = 3};\n"
            "int main(void){ return G.a + G.c; }\n")
        self.assertTrue(ok, proc.stdout)

    def test_bails_on_by_value_param(self):
        ok, _ = self._eliminated(
            "void sink(struct mystruct s);\n"
            "struct mystruct G;\n"
            "int main(void){ G.a = 1; sink(G); return 0; }\n")
        self.assertFalse(ok)

    def test_bails_on_by_value_return(self):
        ok, _ = self._eliminated(
            "struct mystruct make(void);\n"
            "int main(void){ struct mystruct g = make(); return g.a; }\n")
        self.assertFalse(ok)
