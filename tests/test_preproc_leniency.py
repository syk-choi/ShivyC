"""Invalid pp-tokens in dead #if branches and #error text must not break
lexing; only tokens surviving into live code are errors."""

import os
import subprocess
import tempfile
import unittest


def _compile(src):
    d = tempfile.mkdtemp()
    c = os.path.join(d, "t.c")
    with open(c, "w") as f:
        f.write(src)
    out = os.path.join(d, "t")
    p = subprocess.run(["shivyc", c, "-o", out], capture_output=True,
                       text=True)
    return p.returncode, p.stdout + p.stderr, out


class TestPreprocLeniency(unittest.TestCase):
    def test_bad_token_in_dead_branch_ok(self):
        rc, out, exe = _compile(
            "#if 0\nint x = 0...7.;\n#endif\nint main(){ return 5; }")
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([exe]).returncode, 5)

    def test_bad_token_in_dead_error_ok(self):
        rc, out, exe = _compile(
            "#if 0\n#error must be in range 0...7.\n#endif\n"
            "int main(){ return 6; }")
        self.assertEqual(rc, 0)

    def test_live_error_fires_with_message(self):
        rc, out, exe = _compile(
            "#if 1\n#error must be in range 0...7.\n#endif\n"
            "int main(){ return 0; }")
        self.assertNotEqual(rc, 0)
        self.assertIn("must be in range", out)

    def test_live_bad_token_still_errors(self):
        rc, out, exe = _compile("int main(){ int 1bad; return 0; }")
        self.assertNotEqual(rc, 0)
        self.assertIn("unrecognized token", out)

    def test_backtick_in_dead_branch_ok(self):
        rc, out, exe = _compile(
            "#if 0\n#error see `arenas` field\n#endif\nint main(){ return 7; }")
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([exe]).returncode, 7)


class TestCommentDelimiters(unittest.TestCase):
    """Comment delimiters are detected from raw chars, so /*=, */ and //=
    (where a greedy symbol like *= or /= would otherwise hide the delimiter)
    are handled correctly."""

    def test_slash_star_equals(self):
        rc, out, exe = _compile("/*==*/\nint main(){ return 5; }")
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([exe]).returncode, 5)

    def test_banner_comment(self):
        rc, out, exe = _compile(
            "/*========= banner =========*/\nint main(){ return 6; }")
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([exe]).returncode, 6)

    def test_apostrophe_and_equals_in_comment(self):
        rc, out, exe = _compile(
            "/*== they're (== aren't) ==*/\nint main(){ return 7; }")
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([exe]).returncode, 7)

    def test_line_comment_equals(self):
        rc, out, exe = _compile("//= note\nint main(){ return 8; }")
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([exe]).returncode, 8)


class TestDynamicBuiltinMacros(unittest.TestCase):
    def test_line(self):
        rc, out, exe = _compile("int main(void){ return __LINE__; }")
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([exe]).returncode, 1)

    def test_file_compiles_and_runs(self):
        rc, out, exe = _compile(
            "extern int puts(const char*);\n"
            "int main(void){ puts(__FILE__); return 0; }")
        self.assertEqual(rc, 0)
        self.assertEqual(subprocess.run([exe]).returncode, 0)
