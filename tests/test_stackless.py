"""Tests for the stackless / low-overhead calls optimization.

This pass lowers the deeply-nested call pattern (foo -> bar -> boo -> zoo)
using direct calls, tail-call jumps, and frame-pointer omission. It is opt-in
via `-fstackless-calls` and must never change a program's observable behavior.

These tests drive the real pipeline (assemble + link) with the flag on, run
the binary, and inspect the emitted assembly.
"""

import os
import subprocess
import tempfile
import unittest

import shivyc.main
from shivyc.errors import error_collector


class _Args:
    """Mock command-line arguments with stackless calls enabled."""

    show_reg_alloc_perf = False
    variables_on_stack = False
    simd_pack_globals = False
    stackless_calls = True

    def __init__(self, files, output_name):
        self.files = files
        self.output_name = output_name


def _compile_and_run(source, enable=True):
    """Compile `source` (flag on/off); return (exit_code, asm_text)."""
    workdir = tempfile.mkdtemp()
    c_path = os.path.join(workdir, "prog.c")
    out_path = os.path.join(workdir, "prog")
    with open(c_path, "w") as f:
        f.write(source)

    args = _Args([c_path], [out_path])
    args.stackless_calls = enable

    shivyc.main.get_arguments = lambda: args
    error_collector.show = lambda: True
    error_collector.clear()
    rc = shivyc.main.main()
    assert rc == 0, "compilation failed"

    with open(os.path.join(workdir, "prog.s")) as f:
        asm = f.read()
    return subprocess.run([out_path]).returncode, asm


NESTED = """
    int accum;
    void sum() { accum = accum + 1; }
    void foo() { sum(); }
    void bar() { foo(); sum(); }
    void boo() { bar(); sum(); }
    void zoo() { boo(); sum(); }
    int main() {
      accum = 0;
      foo(); bar(); boo(); zoo();
      return accum;          /* 1 + 2 + 3 + 4 = 10 sum-calls */
    }
"""


def _section(asm, name, nxt):
    return asm.split(name + ":")[1].split(nxt + ":")[0]


class TestStackless(unittest.TestCase):
    """Correctness and codegen of the stackless-calls optimization."""

    def test_nested_result_matches(self):
        """Optimized and unoptimized builds return the same value."""
        on, _ = _compile_and_run(NESTED, enable=True)
        off, _ = _compile_and_run(NESTED, enable=False)
        self.assertEqual(on, 10)
        self.assertEqual(off, 10)

    def test_leaf_tail_caller_is_frameless_jmp(self):
        """`foo(){ sum(); }` collapses to a single `jmp sum`, no frame."""
        _, asm = _compile_and_run(NESTED, enable=True)
        foo = _section(asm, "foo", "bar")
        self.assertIn("jmp sum", foo)
        self.assertNotIn("push rbp", foo)   # frameless
        self.assertNotIn("call", foo)       # no call/ret round-trip

    def test_direct_call_no_indirection(self):
        """A regular call to a known function is a direct `call name`."""
        _, asm = _compile_and_run(NESTED, enable=True)
        bar = _section(asm, "bar", "boo")
        self.assertIn("call foo", bar)      # direct
        self.assertNotIn("lea", bar)        # no address-load
        self.assertIn("jmp sum", bar)       # tail call to sum

    def test_tail_call_tears_down_frame_before_jmp(self):
        """A framed function restores rsp/rbp before a tail jmp."""
        _, asm = _compile_and_run(NESTED, enable=True)
        bar = _section(asm, "bar", "boo")
        # The teardown (mov rsp, rbp / pop rbp) must precede the jmp.
        self.assertLess(bar.index("pop rbp"), bar.index("jmp sum"))

    def test_value_returning_tail_call(self):
        """`int f(){ return g(); }` becomes a tail jump and stays correct."""
        prog = """
            int g() { return 7; }
            int f() { return g(); }
            int main() { return f() + 1; }
        """
        rc, asm = _compile_and_run(prog, enable=True)
        self.assertEqual(rc, 8)
        self.assertIn("jmp g", _section(asm, "f", "main"))

    def test_recursion_not_tail_optimized(self):
        """Non-tail recursion stays a call and computes correctly."""
        prog = """
            int fact(int n) {
              if (n <= 1) return 1;
              return n * fact(n - 1);
            }
            int main() { return fact(5); }
        """
        rc, asm = _compile_and_run(prog, enable=True)
        self.assertEqual(rc, 120)
        self.assertIn("call fact", _section(asm, "fact", "main"))

    def test_indirect_call_falls_back(self):
        """Calls through a function pointer use the indirect path."""
        prog = """
            int add1(int x) { return x + 1; }
            int apply(int (*fp)(int), int v) { return fp(v); }
            int main() { return apply(add1, 40); }
        """
        rc, asm = _compile_and_run(prog, enable=True)
        self.assertEqual(rc, 41)
        apply_asm = _section(asm, "apply", "main")
        self.assertIn("call rax", apply_asm)   # indirect, not a name

    def test_disabled_uses_normal_calls(self):
        """With the flag off, the classic lea+call sequence is emitted."""
        _, asm = _compile_and_run(NESTED, enable=False)
        foo = _section(asm, "foo", "bar")
        self.assertIn("call", foo)              # call/ret kept
        self.assertNotIn("jmp sum", foo)        # no tail jump


if __name__ == "__main__":
    unittest.main()
