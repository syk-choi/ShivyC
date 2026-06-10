"""Tests for -O4 near-function scratch storage.

A non-reentrant function holds its register spills in a static per-function
BSS buffer instead of the stack, shrinking (or eliminating) its frame. The
transformation must never change a program's result, and must not apply to
re-entrant or address-taken functions.
"""

import os
import subprocess
import tempfile
import unittest

import shivyc.main
from shivyc.errors import error_collector


class _Args:
    show_reg_alloc_perf = False
    variables_on_stack = False
    simd_pack_globals = False
    stackless_calls = False
    metamorphic = False
    opt_level = 0

    def __init__(self, files, output_name):
        self.files = files
        self.output_name = output_name


def _run(source, opt_level=0):
    workdir = tempfile.mkdtemp()
    c_path = os.path.join(workdir, "prog.c")
    out_path = os.path.join(workdir, "prog")
    with open(c_path, "w") as f:
        f.write(source)
    args = _Args([c_path], [out_path])
    args.opt_level = opt_level
    shivyc.main.get_arguments = lambda: args
    error_collector.show = lambda: True
    error_collector.clear()
    rc = shivyc.main.main()
    assert rc == 0, "compilation failed"
    with open(os.path.join(workdir, "prog.s")) as f:
        asm = f.read()
    return subprocess.run([out_path]).returncode, asm


# A long dependency chain that forces the allocator to spill several values.
SPILLY = """
    int compute(int x) {
      int a = x + 1; int b = a * 2; int c = b - 3; int d = c + a;
      int e = d + b; int f = e + c; int g = f + d; int h = g + e;
      int i = h + f; int j = i + g; int k = j + h; int l = k + i;
      return a + b + c + d + e + f + g + h + i + j + k + l;
    }
    int main() { return compute(1); }
"""


class TestNearScratch(unittest.TestCase):

    def test_result_unchanged(self):
        off, _ = _run(SPILLY, opt_level=0)
        on, _ = _run(SPILLY, opt_level=4)
        self.assertEqual(off, on)

    def test_leaf_spills_to_bss_and_is_frameless(self):
        _, asm = _run(SPILLY, opt_level=4)
        self.assertIn(".comm compute__scratch", asm)
        compute = asm.split("compute:")[1].split("main:")[0]
        self.assertIn("compute__scratch", compute)   # spills in the buffer
        self.assertNotIn("sub rsp", compute)         # no stack frame at all
        self.assertNotIn("push rbp", compute)

    def test_without_o4_uses_stack(self):
        _, asm = _run(SPILLY, opt_level=0)
        compute = asm.split("compute:")[1].split("main:")[0]
        self.assertIn("sub rsp", compute)            # stack frame present
        self.assertNotIn("__scratch", asm)

    def test_nonleaf_keeps_alignment_frame_and_is_correct(self):
        src = """
            int helper(int x) { return x * 3; }
            int worker(int n) {
              int a=n+1; int b=a+2; int c=b+3; int d=c+4;
              int e=d+5; int f=e+6; int g=f+7; int h=g+8;
              int s = helper(a) + helper(b);
              return a+b+c+d+e+f+g+h+s;
            }
            int main() { return worker(2); }
        """
        off, _ = _run(src, opt_level=0)
        on, asm = _run(src, opt_level=4)
        self.assertEqual(off, on)
        worker = asm.split("worker:")[1].split("main:")[0]
        # A non-leaf keeps a minimal frame (push rbp) to preserve 16-byte
        # alignment across its calls, but its spills are in the buffer.
        self.assertIn("push rbp", worker)
        self.assertIn("worker__scratch", worker)

    def test_recursive_excluded(self):
        src = ("int fact(int n) { if (n <= 1) { return 1; }\n"
               "  return n * fact(n - 1); }\n"
               "int main() { return fact(5); }\n")
        rc, asm = _run(src, opt_level=4)
        self.assertEqual(rc, 120)
        self.assertNotIn("fact__scratch", asm)       # reentrant -> excluded

    def test_address_taken_locals_stay_on_stack(self):
        # Cross-object pointer arithmetic depends on stack layout; address-taken
        # locals must not be relocated. (Mirrors feature_tests/pointer_math.c.)
        src = """
            int main() {
              int a = 5, b = 10, c = 15;
              &a; &b; &c;
              if (*(&c + 1) != 10) return 1;
              if (&a - &b != 1) return 9;
              return 0;
            }
        """
        rc, asm = _run(src, opt_level=4)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
