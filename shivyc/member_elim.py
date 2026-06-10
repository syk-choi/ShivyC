"""Whole-program elimination of never-accessed struct members.

When the whole program is compiled together (the cross-TU view), a struct
member that is never read or written through `.`/`->` in any translation unit
occupies space for nothing. This pass detects such members and shrinks the
struct, so programmers can keep one generous struct definition instead of
hand-pruning members with #ifdef.

Removing a struct member changes its layout, which is only sound if the
struct's bytes are never observed except through tracked member accesses. The
analysis is therefore conservative: a struct tag is *eligible* only if, across
the whole program, it is used solely through direct member access on named
objects. Any of the following marks the tag ineligible (it keeps every
member):

  * the address of an instance is taken (`&s`) -- the bytes could then escape
    to memcpy, I/O, a char* cast, pointer arithmetic, etc.;
  * `sizeof` or `__builtin_offsetof` is applied to the type -- the size or a
    later member's offset would change observably;
  * it is initialized with a positional (non-designated) brace initializer --
    removing a middle member would shift the others;
  * it is nested inside another struct/union or an array, or passed/returned
    by value -- its layout is exposed through the enclosing object or the call.

Only anonymous-tag-free named structs participate (members are correlated
across translation units by tag name).

State lives at module scope because it must be shared between the
whole-program analysis pass and the per-file compile that follows.
"""

# True only while the whole-program analysis pass is running.
_collecting = False

# tag -> set of member names accessed anywhere (during analysis)
_accessed = {}
# tags that must keep every member (unsafe to shrink)
_ineligible = set()
# tag -> list of all member names, in declaration order (during analysis)
_all_members = {}

# The result consulted during real compilation:
# tag -> frozenset of member names to remove.
removable = {}

# Whether the optimization is enabled at all (set from the -f flag).
enabled = False


def begin_collection():
    """Start the whole-program analysis pass."""
    global _collecting
    _collecting = True
    _accessed.clear()
    _ineligible.clear()
    _all_members.clear()


def record_access(tag, member):
    """Record that `member` of struct `tag` is accessed (analysis only)."""
    if _collecting and tag is not None:
        _accessed.setdefault(tag, set()).add(member)


def record_all_members(tag, member_names):
    """Record the full member list of struct `tag` (analysis only)."""
    if _collecting and tag is not None and tag not in _all_members:
        _all_members[tag] = list(member_names)


def mark_ineligible(tag):
    """Mark struct `tag` as unsafe to shrink (analysis only)."""
    if _collecting and tag is not None:
        _ineligible.add(tag)


def collecting():
    """Whether the analysis pass is currently running."""
    return _collecting


def finalize():
    """End analysis and compute the removable-member sets.

    Returns the {tag: frozenset(members)} mapping (also stored in `removable`).
    """
    global _collecting
    _collecting = False
    result = {}
    for tag, members in _all_members.items():
        if tag in _ineligible:
            continue
        used = _accessed.get(tag, set())
        rem = [m for m in members if m not in used]
        if rem:
            result[tag] = frozenset(rem)
    return result


def install(mapping):
    """Install the removable-member mapping for the real compile."""
    removable.clear()
    if mapping:
        removable.update(mapping)


def removable_for(tag):
    """Return the frozenset of members to remove from struct `tag`."""
    if not enabled or tag is None:
        return frozenset()
    return removable.get(tag, frozenset())
