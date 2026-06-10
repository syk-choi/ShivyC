"""Tests for the on-disk AST cache and the whole-program call graph.

The cache must be transparent: a warm (cached) compile must produce assembly
byte-identical to a cold compile, and token kinds must survive pickling as
singletons (otherwise identity comparisons in the IL stage break). The call
graph must merge edges across translation units.
"""

import os
import pickle
import subprocess
import tempfile
import unittest

import shivyc.cache as cache
import shivyc.token_kinds as token_kinds
import shivyc.callgraph as callgraph


class _Args:
    show_reg_alloc_perf = False
    variables_on_stack = False
    simd_pack_globals = False
    stackless_calls = False
    metamorphic = False
    opt_level = 0
    include_dirs = []
    print_call_graph = False
    no_cache = False


def _compile_to_asm(c_path, asm_path, cache_dir):
    """Compile a single C file to assembly using the given cache dir."""
    env = dict(os.environ, SHIVYC_CACHE_DIR=cache_dir)
    # -S is not a ShivyC flag; instead compile to an object and keep the .s
    # ShivyC writes next to the source. We drive the real CLI for fidelity.
    out = os.path.splitext(c_path)[0]
    subprocess.run(["shivyc", c_path, "-o", out], env=env,
                   capture_output=True)
    produced = os.path.splitext(c_path)[0] + ".s"
    if os.path.exists(produced):
        with open(produced) as f:
            data = f.read()
        with open(asm_path, "w") as f:
            f.write(data)
        return data
    return None


class TestTokenKindPickle(unittest.TestCase):
    def test_singleton_survives_pickle(self):
        for kind in (token_kinds.char_kw, token_kinds.identifier,
                     token_kinds.number, token_kinds.open_paren,
                     token_kinds.return_kw):
            self.assertIs(pickle.loads(pickle.dumps(kind)), kind)


class TestTokenKey(unittest.TestCase):
    def _tokens(self, src):
        import shivyc.lexer as lexer
        import shivyc.preproc as preproc
        import shivyc.weak_alias as weak_alias
        import shivyc.main as main_mod
        toks = preproc.process(lexer.tokenize(src, "t.c"), "t.c")
        toks, _ = weak_alias.extract_aliases(toks)
        return main_mod._concat_adjacent_strings(toks)

    def test_identical_source_same_key(self):
        a = cache.token_key(self._tokens("int main(){return 1+2;}"))
        b = cache.token_key(self._tokens("int main(){return 1+2;}"))
        self.assertEqual(a, b)

    def test_different_source_different_key(self):
        a = cache.token_key(self._tokens("int main(){return 1+2;}"))
        b = cache.token_key(self._tokens("int main(){return 1+3;}"))
        self.assertNotEqual(a, b)


class TestCacheTransparency(unittest.TestCase):
    def test_cold_warm_asm_identical(self):
        work = tempfile.mkdtemp()
        cache_dir = os.path.join(work, "cache")
        c_path = os.path.join(work, "prog.c")
        with open(c_path, "w") as f:
            f.write("struct P{int x;int y;};"
                    "int add(int a,int b){return a+b;}"
                    "int main(){struct P p={5,37};"
                    "int a[3]={1,2,3};"
                    "return add(p.x,p.y)+a[0]+a[1]+a[2]-6;}")
        cold = _compile_to_asm(c_path, os.path.join(work, "cold.s"), cache_dir)
        warm = _compile_to_asm(c_path, os.path.join(work, "warm.s"), cache_dir)
        self.assertIsNotNone(cold)
        self.assertIsNotNone(warm)
        self.assertEqual(cold, warm)


class TestWholeProgramGraph(unittest.TestCase):
    def test_cross_tu_edge(self):
        work = tempfile.mkdtemp()
        util = os.path.join(work, "util.c")
        mainf = os.path.join(work, "main.c")
        with open(util, "w") as f:
            f.write("int sq(int x){return x*x;}")
        with open(mainf, "w") as f:
            f.write("int sq(int x); int main(){return sq(6);}")
        graph, ok = callgraph.build_program_graph([mainf, util], _Args())
        self.assertTrue(ok)
        self.assertIn("sq", graph.defined)
        self.assertIn("main", graph.defined)
        # main calls sq, which is defined in the other TU.
        self.assertIn("sq", graph.edges.get("main", set()))
        self.assertEqual(graph.undefined_calls(), {})

    def test_recursion_detected(self):
        work = tempfile.mkdtemp()
        f = os.path.join(work, "r.c")
        with open(f, "w") as fh:
            fh.write("int fac(int n){return n<=1?1:n*fac(n-1);}"
                     "int main(){return fac(5);}")
        graph, ok = callgraph.build_program_graph([f], _Args())
        self.assertTrue(graph.reaches_self("fac"))
        self.assertFalse(graph.reaches_self("main"))


if __name__ == "__main__":
    unittest.main()
