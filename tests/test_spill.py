"""Register-allocator scratch-register spilling and 64-bit immediate stores.

The per-command scratch allocator hands out temporary registers to individual
IL commands. When every allocatable register holds a value live across a
command, freeing a scratch register requires parking one such value in memory
for the duration of that command (saved before, restored after). These tests
exercise that path under genuine high register pressure and check, by
differential comparison against gcc, that the save/restore never corrupts a
value -- plus the related fix for moving a >32-bit immediate to memory (which
x86-64 cannot do directly and must route through a register).
"""
import os
import shutil
import subprocess
import tempfile
import unittest


def _build_and_run(src):
    """Compile `src` with shivyc, returning (stdout, exit_code)."""
    d = tempfile.mkdtemp()
    c = os.path.join(d, "t.c")
    out = os.path.join(d, "t")
    with open(c, "w") as f:
        f.write(src)
    proc = subprocess.run(["shivyc", "--no-cache", c, "-o", out],
                          capture_output=True, text=True)
    assert proc.returncode == 0, (
        "shivyc failed:\n" + proc.stdout + proc.stderr)
    run = subprocess.run([out], capture_output=True, text=True, timeout=10)
    return run.stdout, run.returncode & 0xff


def _gcc_run(src):
    """Compile `src` with gcc, returning (stdout, exit_code), or None."""
    if not shutil.which("gcc"):
        return None
    d = tempfile.mkdtemp()
    c = os.path.join(d, "t.c")
    out = os.path.join(d, "t")
    with open(c, "w") as f:
        f.write(src)
    if subprocess.run(["gcc", c, "-o", out],
                      capture_output=True).returncode != 0:
        return None
    run = subprocess.run([out], capture_output=True, text=True, timeout=10)
    return run.stdout, run.returncode & 0xff


# Keeps every value AND its address live across one big expression, forcing the
# allocator to pin all registers and the scratch allocator to spill.
HIGH_PRESSURE = r"""
#include <stdio.h>
int main(){
  long a=1,b=2,c=3,d=4,e=5,f=6,g=7,h=8,i=9,j=10,k=11,l=12,m=13,n=14;
  long *pa=&a,*pb=&b,*pc=&c,*pd=&d,*pe=&e,*pf=&f,*pg=&g,*ph=&h,
       *pi=&i,*pj=&j,*pk=&k,*pl=&l,*pm=&m,*pn=&n;
  long s = *pa+*pb+*pc+*pd+*pe+*pf+*pg+*ph+*pi+*pj+*pk+*pl+*pm+*pn
           + a+b+c+d+e+f+g+h+i+j+k+l+m+n;
  *pa += s; *pn += *pa; *pg += *pn;
  long s2 = (*pa)^(*pb)^(*pc)^(*pd)^(*pe)^(*pf)^(*pg)^(*ph)
            ^(*pi)^(*pj)^(*pk)^(*pl)^(*pm)^(*pn);
  printf("%ld %ld\n", s & 0x7fffffff, s2 & 0x7fffffff);
  return (int)((s ^ s2) & 0xff);
}
"""

# 64-bit immediates that do not fit in a sign-extended 32-bit field, stored to
# memory-homed variables (their addresses are taken).
IMM64 = r"""
#include <stdio.h>
int main(){
  long a = 9223372036854775807L;
  long b = -9223372036854775807L;
  long c = 0x8000000000000002L;
  long d = 0x123456789ABCDEFL;
  long *pa=&a,*pc=&c,*pd=&d;
  *pa ^= 0xFFFFFFFF00000000L;
  printf("%ld %ld %lx %lx\n", a, b,
         (unsigned long)*pc, (unsigned long)*pd);
  return (int)((a ^ b ^ c ^ d) & 0xff);
}
"""


class TestSpill(unittest.TestCase):
    """Scratch spilling and wide-immediate stores match gcc."""

    def _matches_gcc(self, src):
        mine = _build_and_run(src)
        ref = _gcc_run(src)
        if ref is None:
            self.skipTest("gcc unavailable")
        self.assertEqual(mine, ref)

    def test_high_pressure_addrof_matches_gcc(self):
        """A function that pins every register and takes addresses (forcing
        scratch spills) produces the same result as gcc."""
        self._matches_gcc(HIGH_PRESSURE)

    def test_imm64_to_memory_matches_gcc(self):
        """Storing a >32-bit immediate to a memory location matches gcc."""
        self._matches_gcc(IMM64)

    def test_high_pressure_runs_at_O4(self):
        """The same high-pressure program is also correct under -O4 (the
        whole-program/near-scratch path), and matches gcc."""
        d = tempfile.mkdtemp()
        c = os.path.join(d, "t.c")
        out = os.path.join(d, "t")
        with open(c, "w") as f:
            f.write(HIGH_PRESSURE)
        proc = subprocess.run(["shivyc", "-O4", "--no-cache", c, "-o", out],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        run = subprocess.run([out], capture_output=True, text=True, timeout=10)
        ref = _gcc_run(HIGH_PRESSURE)
        if ref is None:
            self.skipTest("gcc unavailable")
        self.assertEqual((run.stdout, run.returncode & 0xff), ref)


if __name__ == "__main__":
    unittest.main()
