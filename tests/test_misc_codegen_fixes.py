"""Regression tests for assorted codegen/type fixes surfaced by musl."""
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


class TestPointerSubtractionQualifiers(unittest.TestCase):
    def test_char_minus_const_char(self):
        # `char *` - `const char *` is valid; qualifiers on the pointed-to
        # type are ignored for pointer difference (musl strcspn).
        rc, err = _run(
            "typedef unsigned long size_t;\n"
            "int main(void){ char b[8]=\"abcdef\"; char *r=b+5;\n"
            " const char *a=b; return (int)(r-a); }\n")
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 5)


class TestAsmReservedSymbolNames(unittest.TestCase):
    def test_functions_named_like_as_operators(self):
        # C identifiers spelled like GNU-as operators (shr, and, ...) must be
        # renamed so the emitted asm assembles (musl qsort has `shr()`).
        rc, err = _run(
            "static int shr(int x,int n){ return x>>n; }\n"
            "static int and(int a,int b){ return a&b; }\n"
            "static int or(int a,int b){ return a|b; }\n"
            "int main(void){ return shr(160,2)+and(7,5)+or(8,1); }\n")  # 40+5+9
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 54)


if __name__ == "__main__":
    unittest.main()


class TestNestedDesignatedInit(unittest.TestCase):
    def test_nested_member_and_index_designators(self):
        rc, err = _run(
            "struct Inner { int a, b; };\n"
            "struct Outer { int tag; struct Inner in; int arr[3]; };\n"
            "int main(void){ struct Outer o = "
            "{ .tag=1, .in.b=9, .in.a=4, .arr[2]=7 };\n"
            " return o.tag + o.in.a + o.in.b + o.arr[2]; }\n")  # 21
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 21)

    def test_anonymous_union_member_designator(self):
        rc, err = _run(
            "struct S { int kind; union { int as_int; void *p; }; int flags; };\n"
            "int main(void){ struct S s = "
            "{ .as_int=77, .flags=5, .kind=3 };\n"
            " return s.kind + s.as_int + s.flags; }\n")  # 85
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 85)


class TestWideStringLiterals(unittest.TestCase):
    def test_wide_string_elements_and_size(self):
        # L"..." has wchar_t (4-byte) elements; indexing and sizeof must agree.
        rc, err = _run(
            "typedef int wchar_t;\n"
            "int main(void){ const wchar_t *w = L\"ABC\";\n"
            " if (sizeof(L\"ABC\") != 16) return 1;\n"   # 4 elems * 4 bytes
            " if (w[3] != 0) return 2;\n"                # null terminator
            " return (w[0]+w[1]+w[2]) & 0xff; }\n")      # 65+66+67=198
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 198)

    def test_wide_char_constant_is_int(self):
        rc, err = _run("int main(void){ return L'A'; }")  # 65
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 65)


class TestCallArgumentMarshalling(unittest.TestCase):
    def test_shift_pattern_does_not_clobber_args(self):
        # Passing (const, a, b, c) where a/b/c already occupy the next argument
        # registers requires hazard-free parallel-move ordering; a naive order
        # loaded the constant over an arg before it was relocated.
        rc, err = _run(
            "long callee(long a,long b,long c,long d){"
            " return a*1000+b*100+c*10+d; }\n"
            "long caller(long x,long y,long z){ return callee(1,x,y,z); }\n"
            "int main(void){ return (int)(caller(2,3,4) % 1000); }\n")  # 234
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 234)

    def test_seven_argument_call(self):
        rc, err = _run(
            "long f7(long a,long b,long c,long d,long e,long f,long g){"
            " return a+b+c+d+e+f+g; }\n"
            "int main(void){ return (int)f7(1,2,3,4,5,6,7); }\n")  # 28
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 28)


class TestInlineAsmLiteralOperand(unittest.TestCase):
    def test_literal_input_operand(self):
        # An immediate input operand (e.g. "a"(1L)) must not crash move
        # scheduling; the dedup key formerly called str() on a LiteralSpot.
        rc, err = _run(
            "int main(void){ long r;\n"
            " __asm__ __volatile__(\"mov %1, %0\" : \"=a\"(r) : \"a\"(42L));\n"
            " return (int)r; }\n")  # 42
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 42)


class TestThreeArgMain(unittest.TestCase):
    def test_three_arg_main_accepted(self):
        rc, err = _run(
            "int main(int argc, char **argv, char **envp){"
            " return argc + (envp != 0); }\n")  # argc>=1, envp!=0 -> >=2
        self.assertIsNotNone(rc, err)
        self.assertGreaterEqual(rc, 2)


class TestConditionalStructOperands(unittest.TestCase):
    def test_conditional_with_struct_operands(self):
        # `cond ? structA : structB` is valid C when both have the same
        # struct type, even if one is const-qualified (CPython _PyStackRef).
        rc, err = _run(
            "struct S { long bits; };\n"
            "struct S make(long x){ struct S s; s.bits = x; return s; }\n"
            "static const struct S NULLS = { 0 };\n"
            "int main(void){ int t=1, f=0;\n"
            " struct S a = t ? make(42) : NULLS;\n"
            " struct S b = f ? make(42) : NULLS;\n"
            " struct S c = t ? NULLS : make(99);\n"
            " return (int)(a.bits + b.bits + c.bits); }\n")  # 42
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 42)


class TestVoidFunctionPointerConversion(unittest.TestCase):
    def test_void_ptr_function_ptr_interconvert(self):
        # GCC extension: void* converts to/from a function pointer and may be
        # compared against one (CPython compares slot void* vs PyCFunction).
        rc, err = _run(
            "typedef int (*fp)(int);\n"
            "static int g(int x){ return x+1; }\n"
            "int main(void){ void *p=(void*)g; fp f=(fp)p; void **s=&p;\n"
            " int eq = (*s == (void*)g);\n"
            " return eq ? f(40) : 0; }\n")  # 41
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 41)


class TestExtensionScannerPreprocDirectives(unittest.TestCase):
    def test_function_name_in_multiline_define_not_a_definition(self):
        # A function-like name used on a continuation line of a #define must
        # not be mistaken for a function definition by the extension scanner
        # (CPython's PyUnicodeError_Check / PyObject_TypeCheck pattern).
        rc, err = _run(
            "int Check(void *o){ return o != 0; }\n"
            "#define M1(P)  \\\n"
            "    Check((P))\n"
            "#define M2(P)    \\\n"
            "    ((void *)(P))\n"
            "int main(void){ int x=5; void *p=M2(&x); return Check(p)+6; }\n")  # 7
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 7)


class TestAlignof(unittest.TestCase):
    def test_alignof_types_and_expr(self):
        rc, err = _run(
            "struct S { char c; int i; double d; };\n"
            "int main(void){ int x;\n"
            " return (int)(_Alignof(char) + _Alignof(int) + _Alignof(double)\n"
            "            + _Alignof(struct S) + _Alignof(x) + _Alignof(int[4])); }\n")
        # 1 + 4 + 8 + 8 + 4 + 4 = 29
        self.assertIsNotNone(rc, err)
        self.assertEqual(rc, 29)
