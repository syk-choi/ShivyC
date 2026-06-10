"""Tests for the ShivyC preprocessor.

These compile and run small programs whose result depends on correct
preprocessing: object- and function-like macros, conditional compilation with
constant-expression evaluation, the ``defined`` operator, ``#undef``,
stringize (``#``), token paste (``##``), variadic macros, and the macro
recursion guard. Each test asserts the program's exit code, so a preprocessing
mistake produces a wrong value rather than passing silently.

Also exercises the lexer's integer-constant support (hex / octal / binary and
u/l suffixes), which the preprocessor relies on because tokenization happens
before macro expansion.
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
    """Compile and run `source`; return its exit code."""
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


class TestObjectMacros(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_run(
            "#define N 5\nint main(){ return N + 1; }"), 6)

    def test_nested(self):
        self.assertEqual(_run(
            "#define A 2\n#define B (A+3)\nint main(){ return B*2; }"), 10)

    def test_hex_in_define(self):
        self.assertEqual(_run(
            "#define MASK 0x0F\nint main(){ return MASK; }"), 15)

    def test_undef_then_redefine(self):
        self.assertEqual(_run(
            "#define X 1\n#undef X\n#define X 7\nint main(){ return X; }"), 7)

    def test_recursion_guard(self):
        # A macro that names itself must not loop forever.
        self.assertEqual(_run(
            "#define FOO FOO\nint main(){ int FOO = 3; return FOO; }"), 3)

    def test_mutual_recursion_guard(self):
        self.assertEqual(_run(
            "#define P Q\n#define Q P\n"
            "int main(){ int P = 5; return P; }"), 5)


class TestFunctionMacros(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_run(
            "#define ADD(a,b) ((a)+(b))\nint main(){ return ADD(3,4); }"), 7)

    def test_nested_invocation(self):
        self.assertEqual(_run(
            "#define SQ(x) ((x)*(x))\nint main(){ return SQ(SQ(2)); }"), 16)

    def test_paste(self):
        self.assertEqual(_run(
            "#define CAT(a,b) a##b\n"
            "int main(){ int xy = 4; return CAT(x,y); }"), 4)

    def test_paste_with_number(self):
        self.assertEqual(_run(
            "#define LBL(n) lbl##n\n"
            "int main(){ int lbl3 = 9; return LBL(3); }"), 9)

    def test_stringize(self):
        # #x -> "hello"; first character is 'h' == 104.
        self.assertEqual(_run(
            "#define S(x) #x\n"
            "int main(){ char *p = S(hello); return p[0]; }"), 104)

    def test_variadic(self):
        self.assertEqual(_run(
            "#define SUM(...) sum(__VA_ARGS__)\n"
            "int sum(int a,int b,int c){return a+b+c;}\n"
            "int main(){ return SUM(2,3,4); }"), 9)

    def test_named_and_variadic(self):
        self.assertEqual(_run(
            "#define LOG(fmt,...) f(fmt,__VA_ARGS__)\n"
            "int f(int a,int b,int c){return a+b+c;}\n"
            "int main(){ return LOG(1,2,3); }"), 6)


class TestConditionals(unittest.TestCase):
    def test_ifdef(self):
        self.assertEqual(_run(
            "#define FEATURE\nint main(){\n#ifdef FEATURE\n"
            "return 9;\n#else\nreturn 0;\n#endif\n}"), 9)

    def test_ifndef(self):
        self.assertEqual(_run(
            "int main(){\n#ifndef NOPE\nreturn 11;\n#endif\nreturn 0;\n}"), 11)

    def test_if_expression(self):
        self.assertEqual(_run(
            "#define LVL 3\nint main(){\n#if LVL >= 2 && LVL < 5\n"
            "return 22;\n#else\nreturn 0;\n#endif\n}"), 22)

    def test_elif_chain(self):
        prog = ("#define V {0}\nint main(){{\n#if V==1\nreturn 1;\n"
                "#elif V==2\nreturn 2;\n#else\nreturn 3;\n#endif\n}}")
        self.assertEqual(_run(prog.format(2)), 2)
        self.assertEqual(_run(prog.format(9)), 3)

    def test_defined_operator(self):
        self.assertEqual(_run(
            "#define HAVE_X\nint main(){\n"
            "#if defined(HAVE_X) && !defined(HAVE_Y)\nreturn 5;\n"
            "#endif\nreturn 0;\n}"), 5)

    def test_nested_conditionals(self):
        self.assertEqual(_run(
            "#define A 1\n#define B 1\nint main(){\n#if A\n#if B\n"
            "return 8;\n#else\nreturn 7;\n#endif\n#endif\nreturn 0;\n}"), 8)

    def test_if_arithmetic(self):
        # Exercises the constant-expression evaluator's operators.
        self.assertEqual(_run(
            "int main(){\n#if (1<<4) + 0xA - (6%4) == 24\n"
            "return 24;\n#else\nreturn 0;\n#endif\n}"), 24)

    def test_line_continuation(self):
        # A directive spanning physical lines via backslash-newline (as musl's
        # features.h does) must be treated as one logical directive.
        self.assertEqual(_run(
            "int main(){\n#if defined(A) || \\\n    !defined(B)\n"
            "return 13;\n#else\nreturn 0;\n#endif\n}"), 13)


class TestLexerIntegerConstants(unittest.TestCase):
    def test_hex_octal_decimal(self):
        self.assertEqual(_run("int main(){ return 0x1F + 010 + 1; }"), 40)

    def test_binary(self):
        self.assertEqual(_run("int main(){ return 0b101; }"), 5)

    def test_suffixes(self):
        self.assertEqual(_run("int main(){ return 10UL + 5L; }"), 15)


if __name__ == "__main__":
    unittest.main()
