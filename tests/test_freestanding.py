"""Tests for freestanding support used by bare-metal/unikernel code.

Covers the bundled `<stddef.h>`/`<stdint.h>` headers and relational/equality
comparison between pointers that differ only in qualifiers (e.g. `char *` vs
`const char *`), which is valid C and appears in freestanding `memmove`
implementations such as Minikraft's `src/kernel/string.c`.
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


def _run(source):
    workdir = tempfile.mkdtemp()
    c_path = os.path.join(workdir, "prog.c")
    out_path = os.path.join(workdir, "prog")
    with open(c_path, "w") as f:
        f.write(source)
    args = _Args([c_path], [out_path])
    shivyc.main.get_arguments = lambda: args
    error_collector.show = lambda: True
    error_collector.clear()
    rc = shivyc.main.main()
    assert rc == 0, "compilation failed"
    return subprocess.run([out_path]).returncode


class TestFreestandingHeaders(unittest.TestCase):
    def test_stddef_size_t(self):
        self.assertEqual(_run(
            "#include <stddef.h>\n"
            "int main(){ size_t n = 5; return (int)n; }"), 5)

    def test_stdint_types(self):
        self.assertEqual(_run(
            "#include <stdint.h>\n"
            "int main(){ uint8_t a = 250; uint32_t b = a + 10;"
            " return (int)(b & 0xFF); }"), 4)


class TestQualifierComparison(unittest.TestCase):
    def test_const_vs_nonconst_pointer(self):
        self.assertEqual(_run(
            "int main(){ char a[4]; char *p = a; const char *q = a + 2;"
            " return p < q ? 1 : 0; }"), 1)

    def test_memmove_overlap(self):
        # The exact freestanding memmove shape (Minikraft string.c), which
        # compares `unsigned char *` against `const unsigned char *`.
        src = (
            "#include <stddef.h>\n"
            "void *memmove(void *dest, const void *src, size_t n){\n"
            "  unsigned char *d = (unsigned char *)dest;\n"
            "  const unsigned char *s = (const unsigned char *)src;\n"
            "  if (d < s) { while (n--) *d++ = *s++; }\n"
            "  else { d += n; s += n; while (n--) *--d = *--s; }\n"
            "  return dest;\n"
            "}\n"
            "int main(){\n"
            "  char b[9]; for (int i=0;i<8;i++) b[i]=\"abcdefgh\"[i]; b[8]=0;\n"
            "  memmove(b+2, b, 6); b[8]=0;\n"
            "  int ok = 1; char *e = \"ababcdef\";\n"
            "  for (int i=0;i<8;i++) if (b[i]!=e[i]) ok=0;\n"
            "  return ok;\n"
            "}")
        self.assertEqual(_run(src), 1)


if __name__ == "__main__":
    unittest.main()
