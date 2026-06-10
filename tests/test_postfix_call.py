"""Postfix operators may follow a function call: f()->m, (*f()).m,
f()->arr[i], f()[i].m."""
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
    p = subprocess.run(["shivyc", c, "-o", out], capture_output=True,
                       text=True)
    if p.returncode != 0:
        return None, p.stdout + p.stderr
    return subprocess.run([out]).returncode, ""


SRC = """
struct S { int gc; int arr[3]; };
static struct S storage = { 42, {7,8,9} };
struct S* getS(void){ return &storage; }
int main(void){
    int a = getS()->gc;
    int b = (*getS()).gc;
    int c = getS()->arr[1];
    int d = getS()[0].gc;
    return a + b + c + d;
}
"""


class TestPostfixAfterCall(unittest.TestCase):
    def test_chains_match_expected(self):
        rc, err = _run(SRC)
        self.assertEqual(rc, 134, err)
