"""Contract-driven, fallback-free SIMD.

The language-extension front-end (shivyc/extensions.py) attaches `assert`-style
contracts to a function's array arguments, e.g. for

    int calc_sum(int *ptr, unsigned int len)
    assert len(ptr) >= 64
    assert not len(ptr) % 4

it records `{'ptr': {'len>=': 64, 'div-by': 4}}`.

GCC and Clang, when they auto-vectorize a reduction like `for(i) v += ptr[i]`,
must emit a scalar remainder loop (and sometimes runtime alignment checks) for
the cases where the length is not a multiple of the SIMD width. Those branches
are the "fallback".

When the compiler can *see the whole call graph* and prove that every call
satisfies the contracts -- for instance by parsing `malloc(N * sizeof(int))` at
the one call site -- the remainder can never run, so it can be omitted. This
module performs that proof and, for a recognized sum-reduction, emits a
fallback-free SSE2 loop (4x int32 per iteration, no scalar tail).

This is a deliberately narrow, verifiable slice: it vectorizes integer sum
reductions whose alignment is *proven*, and otherwise leaves ShivyC's ordinary
scalar codegen untouched.
"""

import shivyc.il_cmds.control as control_cmds
import shivyc.il_cmds.value as value_cmds
import shivyc.il_cmds.math as math_cmds
import shivyc.asm_cmds as asm_cmds
import shivyc.spots as spots


class ProofResult:
    """Outcome of proving a contract function's call sites."""

    def __init__(self, name):
        self.name = name
        self.call_sites = 0
        self.proven = False
        self.reason = ""

    def __str__(self):
        if self.proven:
            return (f"simd-contracts: '{self.name}': contracts proven at all "
                    f"{self.call_sites} call site(s); scalar fallback omitted")
        return (f"simd-contracts: '{self.name}': not proven "
                f"({self.reason}); keeping scalar code")


def analyze(il_code, symbol_table, ext_info):
    """Prove contracts across the call graph.

    Returns a set of function names that are proven SIMD-safe (every call site
    satisfies the contracts) AND whose body is a recognized reduction, so
    asm_gen may emit the fallback-free SSE2 form. Also returns a list of
    human-readable ProofResult reports.
    """
    proven = set()
    reports = []
    if not ext_info or not ext_info.contracts:
        return proven, reports

    name_of = _build_function_names(il_code, symbol_table)

    for fname, arg_contracts in ext_info.contracts.items():
        result = ProofResult(fname)
        if fname not in il_code.commands:
            result.reason = "no definition"
            reports.append(result)
            continue

        elem_size, arg_index = _pointer_arg_info(fname, symbol_table)
        if elem_size is None:
            result.reason = "no pointer argument with a contract"
            reports.append(result)
            continue

        contract = next(iter(arg_contracts.values()))
        sites = _find_call_sites(il_code, name_of, fname)
        result.call_sites = len(sites)

        if not sites:
            result.reason = "no call sites visible"
            reports.append(result)
            continue

        all_ok = True
        for caller, call in sites:
            count = _prove_one_call(
                il_code, name_of, caller, call, arg_index, elem_size)
            if count is None or not _satisfies(count, contract):
                all_ok = False
                result.reason = "a call site could not be proven aligned"
                break

        if all_ok and _is_sum_reduction(il_code.commands[fname]):
            result.proven = True
            proven.add(fname)
        elif all_ok:
            result.reason = "alignment proven but body is not a sum reduction"

        reports.append(result)

    return proven, reports


def _satisfies(count, contract):
    """Check a proven element count against a contract dict."""
    if "len>=" in contract and count < contract["len>="]:
        return False
    if "len<=" in contract and count > contract["len<="]:
        return False
    if "div-by" in contract and count % contract["div-by"] != 0:
        return False
    return True


def _build_function_names(il_code, symbol_table):
    """Map each function ILValue to its name (for resolving call targets)."""
    names = {}
    for val, name in symbol_table.names.items():
        ctype = getattr(val, "ctype", None)
        if ctype is not None and ctype.is_function():
            names[val] = name
    return names


def _pointer_arg_info(fname, symbol_table):
    """Return (element_size, arg_index) for the function's pointer arg."""
    func_val = None
    for val, name in symbol_table.names.items():
        if name == fname and val.ctype.is_function():
            func_val = val
            break
    if func_val is None:
        return None, None
    for i, arg_t in enumerate(func_val.ctype.args):
        if arg_t.is_pointer():
            return arg_t.arg.size, i
    return None, None


def _find_call_sites(il_code, name_of, target):
    """Return [(caller_name, Call), ...] calling `target`."""
    sites = []
    for caller, cmds in il_code.commands.items():
        addr_of = {}  # ptr ILValue -> function name it addresses
        for c in cmds:
            if isinstance(c, value_cmds.AddrOf) and c.var in name_of:
                addr_of[c.output] = name_of[c.var]
            elif isinstance(c, control_cmds.Call):
                tgt = getattr(c, "direct_name", None) or addr_of.get(c.func)
                if tgt == target:
                    sites.append((caller, c))
    return sites


def _prove_one_call(il_code, name_of, caller, call, arg_index, elem_size):
    """Return the proven element count for `call`, or None if unprovable."""
    cmds = il_code.commands[caller]

    # Resolve the pointer argument to a malloc(byte_size) with literal size.
    ptr_val = call.args[arg_index]
    byte_size = _trace_malloc_bytes(il_code, name_of, cmds, ptr_val)
    if byte_size is None:
        return None
    count_from_alloc = byte_size // elem_size

    # The length argument must be a literal that does not exceed the allocation.
    len_val = call.args[1 - arg_index] if len(call.args) > 1 else None
    length = _trace_literal(il_code, cmds, len_val) if len_val else None
    if length is None:
        return None
    if length > count_from_alloc:
        return None  # would read out of bounds; not safe
    return length


def _defs(cmds):
    """Map each ILValue to the command that defines (outputs) it."""
    d = {}
    for c in cmds:
        for o in c.outputs():
            d[o] = c
    return d


def _trace_literal(il_code, cmds, val, depth=0):
    """Follow Set-copies to an integer literal value, or None."""
    if val is None or depth > 16:
        return None
    if val in il_code.literals:
        return il_code.literals[val]
    defn = _defs(cmds).get(val)
    if isinstance(defn, value_cmds.Set):
        return _trace_literal(il_code, cmds, defn.arg, depth + 1)
    return None


def _trace_malloc_bytes(il_code, name_of, cmds, val, depth=0):
    """Follow Set-copies to a malloc() call; return its literal byte size."""
    if val is None or depth > 16:
        return None
    defs = _defs(cmds)
    defn = defs.get(val)
    if isinstance(defn, value_cmds.Set):
        return _trace_malloc_bytes(il_code, name_of, cmds, defn.arg, depth + 1)
    if isinstance(defn, control_cmds.Call):
        addr_of = {}
        for c in cmds:
            if isinstance(c, value_cmds.AddrOf) and c.var in name_of:
                addr_of[c.output] = name_of[c.var]
        tgt = getattr(defn, "direct_name", None) or addr_of.get(defn.func)
        if tgt == "malloc" and defn.args:
            return _trace_literal(il_code, cmds, defn.args[0])
    return None


def _is_sum_reduction(cmds):
    """Conservatively recognize `acc = acc + ptr[i]` over a loop.

    ShivyC lowers `v = v + ptr[i]` as `Add(T, v, load); Set(v, T)`, so the
    accumulator cycle is: a ReadAt loads a value, an Add combines it with some
    value `acc`, and a Set writes the Add's result back into that same `acc`.
    """
    read_outputs = set()
    for c in cmds:
        if isinstance(c, value_cmds.ReadAt):
            read_outputs.add(c.output)

    # Set arg -> output, to find what an Add result is copied into.
    set_targets = {}
    for c in cmds:
        if isinstance(c, value_cmds.Set):
            set_targets.setdefault(c.arg, []).append(c.output)

    for c in cmds:
        if not isinstance(c, math_cmds.Add):
            continue
        ins = c.inputs()
        loads = [i for i in ins if i in read_outputs]
        others = [i for i in ins if i not in read_outputs]
        if not loads or not others:
            continue
        # The Add result must be written back into one of its non-load inputs
        # (the accumulator).
        for acc in others:
            if acc in set_targets.get(c.output, []):
                return True
    return False


# --- SSE2 synthesis -------------------------------------------------------

def synth_sse2_reduce(asm_code, func_ctype):
    """Emit a fallback-free SSE2 int32 sum reduction for (int* ptr, len).

    System V: rdi = ptr, esi = len (a multiple of 4 by contract). The result is
    returned in eax. No scalar remainder loop is emitted -- that is the whole
    point: the contract proof guarantees len % 4 == 0.
    """
    loop = asm_code.get_label()
    raw = [
        "push rbp",
        "mov rbp, rsp",
        "pxor xmm0, xmm0",      # 4-lane int32 accumulator
        "mov ecx, esi",         # ecx = len
        "shr ecx, 2",           # ecx = len / 4  (groups of 4 ints)
        "xor rax, rax",         # rax = byte offset
        loop + ":",
        "movdqu xmm1, [rdi + rax]",
        "paddd xmm0, xmm1",
        "add rax, 16",
        "dec ecx",
        "jnz " + loop,
        # horizontal add of the 4 lanes -> eax
        "movdqa xmm1, xmm0",
        "psrldq xmm1, 8",
        "paddd xmm0, xmm1",
        "movdqa xmm1, xmm0",
        "psrldq xmm1, 4",
        "paddd xmm0, xmm1",
        "movd eax, xmm0",
        "mov rsp, rbp",
        "pop rbp",
        "ret",
    ]
    for line in raw:
        asm_code.add(asm_cmds.Raw(line))
