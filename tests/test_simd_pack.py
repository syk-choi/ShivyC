"""Tests for SIMD bit-packing of small global flags into xmm15.

This feature packs 1-8 bit static global flags (named `name_Nbit`) into the
last SIMD register, giving zero-latency register reads inside hot / interrupt
routines. It is opt-in via the `-fsimd-pack-globals` flag.

These tests drive the real compiler pipeline (assemble + link) with the flag
enabled, run the produced binary, and inspect the emitted assembly.
"""

import os
import subprocess
import tempfile
import unittest

import shivyc.main
from shivyc.errors import error_collector


class _Args:
    """Mock command-line arguments with SIMD packing enabled."""

    show_reg_alloc_perf = False
    variables_on_stack = False
    simd_pack_globals = True

    def __init__(self, files, output_name):
        self.files = files
        self.output_name = output_name


def _compile_and_run(source, enable_pack=True):
    """Compile `source` with packing on/off; return (exit_code, asm_text)."""
    workdir = tempfile.mkdtemp()
    c_path = os.path.join(workdir, "prog.c")
    out_path = os.path.join(workdir, "prog")
    with open(c_path, "w") as f:
        f.write(source)

    args = _Args([c_path], [out_path])
    args.simd_pack_globals = enable_pack

    # Drive the compiler through its normal entry point.
    shivyc.main.get_arguments = lambda: args
    error_collector.show = lambda: True
    error_collector.clear()
    rc = shivyc.main.main()
    assert rc == 0, "compilation failed"

    asm_path = os.path.join(workdir, "prog.s")
    with open(asm_path) as f:
        asm = f.read()

    result = subprocess.run([out_path])
    return result.returncode, asm


class TestSimdPack(unittest.TestCase):
    """Verify correctness and codegen of the SIMD bit-packing feature."""

    PROG = """
        unsigned char ready_1bit;
        unsigned char mode_3bit;
        unsigned char level_4bit;

        int irq_handler() {
          int total = 0;
          if (ready_1bit) {
            total = total + mode_3bit;
            total = total + level_4bit;
          }
          return total;
        }

        int main() {
          ready_1bit = 1;
          mode_3bit = 5;
          level_4bit = 9;
          return irq_handler();
        }
    """

    def test_result_correct_with_packing(self):
        """Packed program returns the same value as plain semantics."""
        rc, _ = _compile_and_run(self.PROG, enable_pack=True)
        self.assertEqual(rc, 14)  # 5 + 9

    def test_result_correct_without_packing(self):
        """The same program returns the same value with packing disabled."""
        rc, asm = _compile_and_run(self.PROG, enable_pack=False)
        self.assertEqual(rc, 14)
        self.assertNotIn("xmm15", asm)  # feature truly inert when off

    def test_hot_function_reads_from_register(self):
        """Inside the hot routine, packed flags are read from xmm15."""
        _, asm = _compile_and_run(self.PROG, enable_pack=True)
        handler = asm.split("irq_handler:")[1].split("main:")[0]
        self.assertIn("movq", handler)
        self.assertIn("xmm15", handler)
        # The packed reads of mode/level must not touch their memory homes.
        self.assertNotIn("[mode_3bit]", handler)
        self.assertNotIn("[level_4bit]", handler)

    def test_main_writes_through_to_memory_and_register(self):
        """Writes update both the authoritative byte and xmm15."""
        _, asm = _compile_and_run(self.PROG, enable_pack=True)
        main = asm.split("main:")[1]
        self.assertIn("BYTE PTR [ready_1bit]", main)   # authoritative byte
        self.assertIn("movq xmm15", main)              # register mirror
        self.assertIn("__simd_pack_store", main)       # memory mirror

    def test_non_hot_function_uses_memory(self):
        """A non-hot reader uses memory, not the register fast path."""
        prog = """
            unsigned char a_2bit;
            unsigned char b_5bit;
            int plain_reader() { return a_2bit + b_5bit; }
            int sensor_callback() { return a_2bit + b_5bit; }
            int main() {
              a_2bit = 3; b_5bit = 20;
              return plain_reader() + sensor_callback();
            }
        """
        rc, asm = _compile_and_run(prog, enable_pack=True)
        self.assertEqual(rc, 46)  # 23 + 23, both paths agree
        plain = asm.split("plain_reader:")[1].split("sensor_callback:")[0]
        self.assertIn("[a_2bit]", plain)   # memory read
        self.assertNotIn("xmm15", plain)   # no register fast path
        hot = asm.split("sensor_callback:")[1].split("main:")[0]
        self.assertIn("xmm15", hot)        # register fast path

    def test_overlarge_and_unmarked_globals_unpacked(self):
        """Out-of-range and unmarked globals stay ordinary globals."""
        prog = """
            unsigned char ok_4bit;
            unsigned char too_9bit;
            unsigned char plain;
            int compute_handler() { return ok_4bit + too_9bit + plain; }
            int main() {
              ok_4bit = 7; too_9bit = 100; plain = 50;
              return compute_handler();
            }
        """
        rc, asm = _compile_and_run(prog, enable_pack=True)
        self.assertEqual(rc, 157)
        hot = asm.split("compute_handler:")[1].split("main:")[0]
        self.assertNotIn("[ok_4bit]", hot)   # packed -> register
        self.assertIn("[too_9bit]", hot)     # 9 bits -> memory
        self.assertIn("[plain]", hot)        # unmarked -> memory

    def test_hot_write_then_read(self):
        """A hot routine can write through and read back a packed flag."""
        prog = """
            unsigned char counter_8bit;
            int tick_handler() {
              counter_8bit = counter_8bit + 1;
              return counter_8bit;
            }
            int main() {
              counter_8bit = 41;
              return tick_handler();
            }
        """
        rc, _ = _compile_and_run(prog, enable_pack=True)
        self.assertEqual(rc, 42)


if __name__ == "__main__":
    unittest.main()
