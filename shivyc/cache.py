"""On-disk cache of parsed ASTs, to speed up recompilation.

Parsing (recursive-descent with backtracking) is the most expensive front-end
step, and it depends only on the post-preprocessing token stream. We therefore
key the cache on a hash of that token stream: identical tokens always produce
an identical AST, and the hash naturally incorporates the contents of every
included header (they have already been spliced into the token stream by the
preprocessor). Cache entries are pickled ASTs under a directory in /tmp.

The cache is best-effort: any failure to read, write, or unpickle simply falls
back to parsing from scratch, so a stale or corrupt entry can never produce a
wrong result -- at worst it is ignored.
"""

import hashlib
import os
import pickle

_CACHE_DIR = os.environ.get("SHIVYC_CACHE_DIR", "/tmp/shivyc-cache")

# Bump when the AST representation or parser changes in a way that would make
# previously-cached trees invalid.
_CACHE_VERSION = "1"


def _ensure_dir():
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        return True
    except OSError:
        return False


def token_key(tokens):
    """Return a stable hex digest for a post-preprocessing token stream."""
    h = hashlib.sha256()
    h.update(_CACHE_VERSION.encode())
    for t in tokens:
        # kind is identified by its text_repr; content/rep capture the spelling.
        h.update(b"\x00")
        h.update(str(getattr(t.kind, "text_repr", t.kind)).encode())
        h.update(b"\x01")
        h.update(str(getattr(t, "content", "")).encode())
    return h.hexdigest()


def _path_for(key):
    return os.path.join(_CACHE_DIR, key + ".ast.pkl")


def load_ast(key):
    """Return the cached AST for `key`, or None on any miss/error."""
    try:
        with open(_path_for(key), "rb") as f:
            return pickle.load(f)
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError,
            ImportError, ValueError):
        return None


def store_ast(key, ast):
    """Pickle `ast` under `key`. Best-effort; failures are ignored."""
    if not _ensure_dir():
        return
    tmp = _path_for(key) + ".tmp.%d" % os.getpid()
    try:
        with open(tmp, "wb") as f:
            pickle.dump(ast, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, _path_for(key))  # atomic publish
    except (OSError, pickle.PicklingError, TypeError):
        try:
            os.remove(tmp)
        except OSError:
            pass
