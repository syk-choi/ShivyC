"""Tests for weak aliases (`__attribute__((weak, alias("target")))`).

The alias is emitted as `.weak` / `.set` assembler directives. These tests
compile and run programs where calling the alias must reach the target, and
also check the token-level extraction (including musl's `__typeof`-based
`weak_alias` form, which is recorded even though its declaration is dropped).
"""

import os
import subprocess
import tempfile
import unittest

import shivyc.main
import shivyc.lexer as lexer
import shivyc.preproc as preproc
import shivyc.weak_alias as weak_alias
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


def _aliases(source):
    error_collector.clear()
    toks = preproc.process(lexer.tokenize(source, "t.c"), "t.c")
    _, aliases = weak_alias.extract_aliases(toks)
    return aliases


class TestWeakAlias(unittest.TestCase):
    def test_weak_alias_call(self):
        self.assertEqual(_run(
            "int __real_impl(int x){ return x + 100; }\n"
            "extern int my_alias(int)"
            " __attribute__((__weak__, __alias__(\"__real_impl\")));\n"
            "int main(){ return my_alias(5); }"), 105)

    def test_nonweak_alias_call(self):
        self.assertEqual(_run(
            "int realfn(int x){ return x * 2; }\n"
            "extern int af(int) __attribute__((alias(\"realfn\")));\n"
            "int main(){ return af(21); }"), 42)

    def test_generic_attribute_still_ignored(self):
        self.assertEqual(_run(
            "int x __attribute__((aligned(16))) = 7; int main(){ return x; }"),
            7)

    def test_extracts_alias_metadata(self):
        aliases = _aliases(
            "int realfn(int x){ return x; }\n"
            "extern int af(int) __attribute__((alias(\"realfn\")));\n")
        self.assertIn(("af", "realfn", False), aliases)

    def test_weak_flag_recorded(self):
        aliases = _aliases(
            "int impl(void);\n"
            "extern int a(void)"
            " __attribute__((__weak__, __alias__(\"impl\")));\n")
        self.assertIn(("a", "impl", True), aliases)

    def test_musl_typeof_form(self):
        # musl's weak_alias expands to `extern __typeof(old) new __attribute__
        # ((weak, alias("old")))`. We cannot parse __typeof, so the declaration
        # is dropped, but the alias must still be recorded.
        aliases = _aliases(
            "int __stpcpy(char *a, char *b);\n"
            "extern __typeof(__stpcpy) stpcpy"
            " __attribute__((__weak__, __alias__(\"__stpcpy\")));\n")
        self.assertIn(("stpcpy", "__stpcpy", True), aliases)


if __name__ == "__main__":
    unittest.main()
