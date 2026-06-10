"""Multi-character character constants are valid C (C11 6.4.4.4p10) with an
implementation-defined value; ShivyC packs the bytes big-endian into a signed
int, matching gcc (e.g. 'ab' == 0x6162). This also keeps the lexer tolerant of
`'...'` text inside skipped conditional groups (CPython's `# error C 'size_t'
...`), which the lexer scans before the preprocessor discards the inactive
group."""
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
    p = subprocess.run(["shivyc", c, "-o", out], capture_output=True, text=True)
    if p.returncode != 0:
        return None, p.stdout + p.stderr
    return subprocess.run([out]).returncode, ""


class TestMultiCharConst(unittest.TestCase):
    def test_packed_value_matches_gcc(self):
        rc, err = _run(
            "int main(void){ return ('ab' == 0x6162)"
            " && ('abcd' == 0x61626364) ? 42 : 7; }\n")
        self.assertEqual(rc, 42, err)

    def test_single_char_unchanged(self):
        rc, err = _run("int main(void){ return 'A'; }\n")
        self.assertEqual(rc, 65, err)

    def test_charconst_in_skipped_branch(self):
        # The apostrophes in the not-taken #error branch must not break lexing.
        rc, err = _run(
            "#define N 8\n"
            "#if (N == 8)\n"
            "int x = 1;\n"
            "#else\n"
            "# error C 'size_t' size should be either 4 or 8!\n"
            "#endif\n"
            "int main(void){ return x; }\n")
        self.assertEqual(rc, 1, err)
