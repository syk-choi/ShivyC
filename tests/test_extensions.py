"""Tests for the C language-extension front-end (shivyc/extensions.py).

These exercise the source pre-pass directly: specifier recognition, ast-based
contract parsing, byte/line-offset preservation, and correct handling of
tricky shapes (function-pointer params, call sites, prototypes).
"""

import unittest

from shivyc.extensions import preprocess_extensions, ExtensionError


class TestExtensions(unittest.TestCase):
    """The extension pre-pass extracts metadata and blanks regions cleanly."""

    def test_specifiers_recorded(self):
        src = ("void f() __stackless__ { }\n"
               "void g() __metamorphic__ { }\n")
        clean, info = preprocess_extensions(src)
        self.assertEqual(info.attrs_of("f"), {"stackless"})
        self.assertEqual(info.attrs_of("g"), {"metamorphic"})
        self.assertNotIn("__stackless__", clean)
        self.assertNotIn("__metamorphic__", clean)

    def test_contracts_parsed_with_ast(self):
        src = ("int calc(int *ptr, unsigned int len)\n"
               "assert len(ptr) >= 64\n"
               "assert len(ptr) <= 4096\n"
               "assert not len(ptr) % 4\n"
               "{ return 0; }\n")
        _, info = preprocess_extensions(src)
        self.assertEqual(
            info.contracts_of("calc")["ptr"],
            {"len>=": 64, "len<=": 4096, "div-by": 4})

    def test_offsets_preserved(self):
        src = ("int calc(int *ptr)\n"
               "assert len(ptr) >= 8\n"
               "{ return 0; }\n")
        clean, _ = preprocess_extensions(src)
        self.assertEqual(len(clean), len(src))
        self.assertEqual(clean.count("\n"), src.count("\n"))

    def test_ordinary_functions_untouched(self):
        src = "int main() { return foo() + bar(); }\n"
        clean, info = preprocess_extensions(src)
        self.assertEqual(clean, src)
        self.assertFalse(info)

    def test_function_pointer_param_ignored(self):
        # The inner parens of a function-pointer parameter must not confuse the
        # scanner into treating this as an extended definition.
        src = "int apply(int (*fp)(int), int v) { return fp(v); }\n"
        clean, info = preprocess_extensions(src)
        self.assertEqual(clean, src)
        self.assertFalse(info)

    def test_len_inside_assert_not_matched_as_header(self):
        # `len(ptr)` looks like a call; it must not be picked up as a function.
        src = ("int calc(int *ptr)\n"
               "assert not len(ptr) % 8\n"
               "{ return 0; }\n")
        _, info = preprocess_extensions(src)
        self.assertIn("calc", info.contracts)
        self.assertNotIn("len", info.contracts)
        self.assertNotIn("len", info.attrs)

    def test_combined_specifier_and_contract(self):
        src = ("int hot(int *p) __stackless__\n"
               "assert not len(p) % 16\n"
               "{ return 0; }\n")
        _, info = preprocess_extensions(src)
        self.assertEqual(info.attrs_of("hot"), {"stackless"})
        self.assertEqual(info.contracts_of("hot")["p"], {"div-by": 16})

    def test_malformed_contract_raises(self):
        src = ("int calc(int *p)\n"
               "assert len(p) > 7\n"   # > is not a supported comparison
               "{ return 0; }\n")
        with self.assertRaises(ExtensionError):
            preprocess_extensions(src)

    def test_prototype_not_treated_as_definition(self):
        # A prototype ends in ';', not '{', so it is never an extension.
        src = "int calc(int *p);\nint main() { return 0; }\n"
        clean, info = preprocess_extensions(src)
        self.assertEqual(clean, src)
        self.assertFalse(info)


if __name__ == "__main__":
    unittest.main()
