"""SIMD bit-packing of small global variables into the last SIMD register.

This module integrates an idea explored in jitbit (Brett Hartshorn) and the
OpenSourceJesus C-Compiler: small, frequently-read global "flag" variables can
be co-located inside an SIMD register that ordinary compilers leave untouched
(``xmm15``). Reads in hot/interrupt routines then become register-only bit
extractions instead of memory loads, eliminating the memory latency / pipeline
stalls that ordinary global access incurs.

Design (kept deliberately conservative so the rest of ShivyC is unaffected):

* A global qualifies if it has static storage, occupies a single byte, and its
  name ends in ``_Nbit`` with ``1 <= N <= 8`` (e.g. ``ready_1bit``,
  ``mode_3bit``). This convention needs no new type-system support, so ShivyC
  parses these programs unchanged.
* Each qualifying global keeps its normal one-byte memory home. That byte stays
  authoritative, so every existing IL command (cmp, arithmetic, address-of,
  ...) keeps working with zero risk.
* On top of that we maintain ``xmm15`` as a packed cache plus an 8-byte memory
  mirror (``__simd_pack_store``). Every write to a packed global is written
  through to all three. Reads inside hot/interrupt functions are served from
  ``xmm15`` (no memory read). ``xmm15`` is refreshed from the mirror at the top
  of each hot function and after each call, which keeps the optimization
  correct even though xmm8-15 are caller-saved in the System V ABI.

The whole feature is opt-in via the ``-fsimd-pack-globals`` flag.
"""

import re

import shivyc.asm_cmds as asm_cmds
from shivyc.spots import RegSpot, MemSpot, LiteralSpot


#: The SIMD register used to hold packed flags. Standard compilers essentially
#: never allocate xmm15 for scalar code, so it is "free real estate".
PACK_REG = "xmm15"

#: Symbol backing the in-memory mirror of PACK_REG.
STORE_SYMBOL = "__simd_pack_store"

#: Total packed bits must fit in the low 64 bits so a single ``movq`` moves the
#: whole field set between the GPR file and the SIMD register.
MAX_PACK_BITS = 64

#: Naming convention: a one-byte global whose name ends in ``_Nbit``.
_NAME_RE = re.compile(r"_(\d+)bit$")

#: Hot / interrupt routines whose reads should come from the register. Mirrors
#: the OpenSourceJesus heuristic, plus an explicit ``_hot`` suffix for testing.
_HOT_RE = [
    re.compile(r"^isr_"),
    re.compile(r"^irq_"),
    re.compile(r"^interrupt_"),
    re.compile(r"_handler$"),
    re.compile(r"_callback$"),
    re.compile(r"_hot$"),
]


def is_hot_function(name):
    """Return whether `name` looks like a hot / interrupt routine."""
    return any(p.search(name) for p in _HOT_RE)


class Slot:
    """One packed variable's position within PACK_REG."""

    def __init__(self, name, start_bit, bits):
        self.name = name
        self.start_bit = start_bit
        self.bits = bits

    @property
    def mask(self):
        """Low-aligned mask covering `bits` bits."""
        return (1 << self.bits) - 1


class SimdPackLayout:
    """Assignment of qualifying globals to bit ranges within PACK_REG."""

    def __init__(self):
        self.slots = {}      # name -> Slot
        self.order = []      # names, in packing order
        self._next_bit = 0
        #: When frozen (a whole-program layout shared across TUs), `consider`
        #: never adds new slots -- the bit assignment is fixed for every unit.
        self.frozen = False

    def consider(self, name, size):
        """Try to assign `name` (a static global of `size` bytes) a slot.

        Returns True if the variable was packed.
        """
        if name in self.slots:
            return True
        if self.frozen:
            return False
        if size != 1:
            return False
        m = _NAME_RE.search(name)
        if not m:
            return False
        bits = int(m.group(1))
        if not (1 <= bits <= 8):
            return False
        if self._next_bit + bits > MAX_PACK_BITS:
            return False  # register full; leave as an ordinary global

        slot = Slot(name, self._next_bit, bits)
        self.slots[name] = slot
        self.order.append(name)
        self._next_bit += bits
        return True

    def is_packed(self, name):
        """Return whether `name` is a packed global."""
        return name in self.slots

    @property
    def active(self):
        """Return whether any variable was packed."""
        return bool(self.slots)

    # -- spot helpers -----------------------------------------------------

    @staticmethod
    def packed_name(spot):
        """Return the symbol name if `spot` is a named-memory spot, else None."""
        if isinstance(spot, MemSpot) and isinstance(spot.base, str):
            return spot.base
        return None

    def slot_for_spot(self, spot):
        """Return the Slot for `spot`, or None if it is not a packed global."""
        name = self.packed_name(spot)
        if name is None:
            return None
        return self.slots.get(name)

    # -- code emission ----------------------------------------------------

    def emit_store_decl(self, asm_code, shared=False):
        """Declare the 8-byte memory mirror for PACK_REG.

        When `shared` (whole-program packing across several TUs), the mirror is
        a non-local common symbol so the linker merges every unit's declaration
        into a single shared object; otherwise it stays translation-unit-local.
        """
        asm_code.add_comm(STORE_SYMBOL, 8, local=not shared)

    def emit_startup_pack(self, asm_code):
        """Pack the authoritative bytes into PACK_REG once, at program start.

        The per-variable bytes already carry any static initializers, so this
        reads them once and seeds both PACK_REG and the memory mirror.
        """
        asm_code.add(asm_cmds.Comment(
            "SIMD pack: seed " + PACK_REG + " from initial flag values"))
        acc = RegSpot("rax")
        tmp = RegSpot("rcx")
        a8 = acc.asm_str(8)
        t8 = tmp.asm_str(8)
        asm_code.add(asm_cmds.Raw("xor " + a8 + ", " + a8))
        for name in self.order:
            slot = self.slots[name]
            asm_code.add(asm_cmds.Raw(
                "movzx " + t8 + ", BYTE PTR [" + name + "]"))
            asm_code.add(asm_cmds.Raw(
                "and " + t8 + ", " + str(slot.mask)))
            if slot.start_bit:
                asm_code.add(asm_cmds.Raw(
                    "shl " + t8 + ", " + str(slot.start_bit)))
            asm_code.add(asm_cmds.Raw("or " + a8 + ", " + t8))
        asm_code.add(asm_cmds.Raw("movq " + PACK_REG + ", " + a8))
        asm_code.add(asm_cmds.Raw(
            "movq QWORD PTR [" + STORE_SYMBOL + "], " + PACK_REG))

    def emit_refresh(self, asm_code):
        """Reload PACK_REG from the memory mirror (one aligned 64-bit read)."""
        asm_code.add(asm_cmds.Comment(
            "SIMD pack: refresh " + PACK_REG + " (1 read covers all flags)"))
        asm_code.add(asm_cmds.Raw(
            "movq " + PACK_REG + ", QWORD PTR [" + STORE_SYMBOL + "]"))

    def emit_read(self, asm_code, slot, dst_reg):
        """Extract `slot` from PACK_REG into the 64-bit GPR `dst_reg`.

        No memory is touched: this is the zero-latency read path.
        """
        d8 = dst_reg.asm_str(8)
        asm_code.add(asm_cmds.Comment(
            "SIMD pack: zero-latency read " + slot.name))
        asm_code.add(asm_cmds.Raw("movq " + d8 + ", " + PACK_REG))
        if slot.start_bit:
            asm_code.add(asm_cmds.Raw("shr " + d8 + ", " + str(slot.start_bit)))
        asm_code.add(asm_cmds.Raw("and " + d8 + ", " + str(slot.mask)))

    def emit_write(self, asm_code, slot, val_reg, acc_reg, msk_reg):
        """Write the value already in `val_reg` into `slot`.

        Updates the authoritative byte, PACK_REG, and the memory mirror.
        `val_reg`, `acc_reg`, and `msk_reg` are three distinct scratch GPRs
        (obtained safely from the register allocator); all may be clobbered.
        """
        v8 = val_reg.asm_str(8)
        v1 = val_reg.asm_str(1)
        a8 = acc_reg.asm_str(8)
        m8 = msk_reg.asm_str(8)

        asm_code.add(asm_cmds.Comment(
            "SIMD pack: write-through " + slot.name))
        # value &= mask
        asm_code.add(asm_cmds.Raw("and " + v8 + ", " + str(slot.mask)))
        # authoritative byte store (keeps the ordinary IL paths correct)
        asm_code.add(asm_cmds.Raw(
            "mov BYTE PTR [" + slot.name + "], " + v1))
        # acc = PACK_REG with this field cleared
        asm_code.add(asm_cmds.Raw("movq " + a8 + ", " + PACK_REG))
        # msk = ~(mask << start)  (built without a 64-bit immediate)
        asm_code.add(asm_cmds.Raw("mov " + m8 + ", " + str(slot.mask)))
        if slot.start_bit:
            asm_code.add(asm_cmds.Raw("shl " + m8 + ", " + str(slot.start_bit)))
        asm_code.add(asm_cmds.Raw("not " + m8))
        asm_code.add(asm_cmds.Raw("and " + a8 + ", " + m8))
        # shift value into position and OR it in
        if slot.start_bit:
            asm_code.add(asm_cmds.Raw("shl " + v8 + ", " + str(slot.start_bit)))
        asm_code.add(asm_cmds.Raw("or " + a8 + ", " + v8))
        asm_code.add(asm_cmds.Raw("movq " + PACK_REG + ", " + a8))
        asm_code.add(asm_cmds.Raw(
            "movq QWORD PTR [" + STORE_SYMBOL + "], " + PACK_REG))
