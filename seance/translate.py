"""Translate a whole COBOL program into Python that runs on seance.rt.

Deterministic and rule-based. Every paragraph becomes a function, every statement one or a few lines tagged
with the COBOL line it came from (# Lnn). Data stays byte-accurate through the runtime, so packed decimal,
binary, REDEFINES, tables and group moves keep COBOL's behavior. A statement the translator cannot convert
becomes S.unsupported(...), which raises NotImplementedError naming the line: a check fails loudly there
instead of passing quietly. The checker, not this file, decides whether the result is right.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .cobol_num import ROUND_MODES
from .cobol_src import read_source, normalize
from .layout import Item, parse_entries, walk
from .model import ROOT, ModelError, ProgramModel, load_model

TEXT_FUNCTIONS = {"UPPER_CASE", "LOWER_CASE", "REVERSE", "TRIM", "LENGTH", "NUMVAL", "NUMVAL_C", "ORD"}

VERBS = {
    "MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "IF", "EVALUATE", "PERFORM", "WRITE", "READ", "OPEN",
    "CLOSE", "DISPLAY", "INITIALIZE", "CONTINUE", "EXIT", "STOP", "GO", "GOBACK", "SET", "ACCEPT", "STRING", "UNSTRING",
    "INSPECT", "CALL", "NEXT", "REWRITE", "DELETE", "START", "RETURN", "RELEASE", "SORT", "MERGE", "CANCEL", "ALTER",
    "ENTRY", "EXEC", "SEARCH", "INITIATE", "GENERATE", "TERMINATE", "USE", "COPY",
}
ENDERS = {"ELSE", "END-IF", "WHEN", "END-EVALUATE", "END-PERFORM", "END-COMPUTE", "END-ADD", "END-SUBTRACT", "END-MULTIPLY",
          "END-DIVIDE", "END-READ", "END-WRITE", "END-STRING", "END-UNSTRING", "END-CALL", "END-SEARCH", "END-ACCEPT",
          "END-DISPLAY", "END-EXEC", "END-DELETE", "END-REWRITE", "END-START", "END-RETURN"}
FIGURATIVE = {"SPACE": "SPACE", "SPACES": "SPACE", "ZERO": "ZERO", "ZEROS": "ZERO", "ZEROES": "ZERO",
              "HIGH-VALUE": "HIGH", "HIGH-VALUES": "HIGH", "LOW-VALUE": "LOW", "LOW-VALUES": "LOW",
              "QUOTE": "QUOTE", "QUOTES": "QUOTE", "NULL": "LOW", "NULLS": "LOW"}
RESERVED = VERBS | ENDERS | set(FIGURATIVE) | {
    "TO", "FROM", "BY", "INTO", "GIVING", "ROUNDED", "ON", "NOT", "SIZE", "ERROR", "AT", "END", "THEN", "AND", "OR", "IS",
    "OTHER", "THRU", "THROUGH", "TIMES", "UNTIL", "VARYING", "WITH", "TEST", "BEFORE", "AFTER", "TRUE", "FALSE", "OF", "IN",
    "EQUAL", "GREATER", "LESS", "THAN", "POSITIVE", "NEGATIVE", "NUMERIC", "ALPHABETIC", "REMAINDER", "CORRESPONDING",
    "CORR", "ADVANCING", "LINE", "LINES", "PAGE", "RECORD", "INPUT", "OUTPUT", "I-O", "EXTEND", "RUN", "ALSO", "ALL",
    "FUNCTION", "UPON", "NO", "REPLACING", "INVALID", "KEY", "PARAGRAPH", "SECTION", "PROGRAM", "DELIMITED", "POINTER",
    "OVERFLOW", "TALLYING", "LEADING", "FIRST", "CHARACTERS", "INITIAL", "CONVERTING", "COUNT", "DELIMITER", "UP", "DOWN",
    "DEPENDING", "DATE", "TIME", "DAY", "DAY-OF-WEEK", "CONSOLE", "SYSIN", "SYSOUT", "SYSERR", "EOP", "END-OF-PAGE",
    "LOCK", "REEL", "UNIT", "REMOVAL", "WITHOUT", "REWIND", "CYCLE", "YYYYMMDD", "YYYYDDD", "USING", "RETURNING",
    "RETURN-CODE",
}


class Unsupported(Exception):
    pass


@dataclass
class Tok:
    kind: str  # word, str, num, op, end
    value: str
    line: int
    raw: str = ""


_TOKEN = re.compile(
    r"""(?P<ws>[\s,;]+)
      | (?P<hex>[xX](?:"[0-9A-Fa-f]*"|'[0-9A-Fa-f]*'))
      | (?P<str>"(?:[^"]|"")*"|'(?:[^']|'')*')
      | (?P<num>(?:\d+\.\d+|\.\d+|\d+)E[+-]?\d+(?![A-Za-z0-9_-])|\d+\.\d+|\.\d+|\d+(?![A-Za-z0-9_-]))
      | (?P<op>\*\*|>=|<=|<>|[()+\-*/=<>:&])
      | (?P<word>[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]|[A-Za-z0-9])
    """,
    re.X,
)


_NUMBER = re.compile(r"(?:\d+\.\d+|\.\d+|\d+)(?![A-Za-z0-9_-])")


def tokenize_lines(lines) -> list[Tok]:
    """Tokens with their own source line. A period followed by a space or the end of a line ends a sentence."""
    out: list[Tok] = []
    for ln in lines:
        if ln.comment:
            continue
        text, line, pos = ln.text, ln.number, 0
        while pos < len(text):
            if text[pos] == "." and (pos + 1 == len(text) or text[pos + 1] in " \t"):
                out.append(Tok("end", ".", line))
                pos += 1
                continue
            m = _TOKEN.match(text, pos)
            if not m:
                raise Unsupported(f"line {line}: cannot read {text[pos:pos + 20]!r}")
            if m.lastgroup == "op" and m.group() in ("+", "-") and pos and text[pos - 1] in " \t" and out and (
                    out[-1].kind in ("word", "num", "str") or (out[-1].kind == "op" and out[-1].value == ")")):
                n = _NUMBER.match(text, pos + 1)  # `3 -14`: after an operand, a sign hugging a number belongs to the number
                if n:
                    out.append(Tok("num", ("-" if m.group() == "-" else "") + n.group(), line, m.group() + n.group()))
                    pos = n.end()
                    continue
            pos = m.end()
            kind = m.lastgroup
            if kind == "ws":
                continue
            value = m.group()
            if kind == "str":
                q = value[0]
                value = value[1:-1].replace(q + q, q)
            elif kind == "hex":
                kind, value = "str", bytes.fromhex(value[2:-1]).decode("latin-1")
            elif kind == "word":
                value = value.upper()
            out.append(Tok(kind, value, line, m.group()))
    if out and out[-1].kind != "end":
        out.append(Tok("end", ".", out[-1].line))
    return out


# ---------------------------------------------------------------- data names

@dataclass
class Names:
    by_name: dict[str, list[Item]] = field(default_factory=dict)
    key: dict[int, str] = field(default_factory=dict)  # id(item) -> unique key
    items: dict[str, Item] = field(default_factory=dict)  # key -> item
    conds: dict[str, tuple] = field(default_factory=dict)  # condition key -> (item key, choices, FALSE value)
    cond_items: dict[str, list] = field(default_factory=dict)  # condition name -> [(item, item key, condition key)]
    classes: dict[str, str] = field(default_factory=dict)  # SPECIAL-NAMES CLASS name -> the characters it allows
    switch_conds: dict[str, tuple] = field(default_factory=dict)  # switch condition -> (switch number, ON STATUS?)
    switch_names: dict[str, int] = field(default_factory=dict)  # switch mnemonic -> switch number
    symbolic: dict[str, str] = field(default_factory=dict)  # SYMBOLIC CHARACTERS name -> the character
    devices: dict[str, str] = field(default_factory=dict)  # mnemonic -> device
    indexes: dict[str, str] = field(default_factory=dict)  # index name -> table item key
    files: dict[str, object] = field(default_factory=dict)  # FD name -> FileDef
    file_buffer: dict[str, str] = field(default_factory=dict)  # FD name -> its record area (shared by SAME RECORD AREA)
    debug_sections: set = field(default_factory=set)  # USE FOR DEBUGGING sections, where DEBUG-ITEM may be read
    linage_items: dict = field(default_factory=dict)  # file name -> its LINAGE-COUNTER item
    alphabets: dict = field(default_factory=dict)  # SPECIAL-NAMES ALPHABET name -> weights of the 256 bytes (None: native)

    def add(self, it: Item, buffer: str) -> None:
        self.by_name.setdefault(it.name, []).append(it)
        it.record = buffer

    def finish(self) -> None:
        for name, its in self.by_name.items():
            for i, it in enumerate(its):
                k = name if len(its) == 1 else f"{name}@{(it.parent.name if it.parent else it.record)}"
                if k in self.items:
                    k = f"{k}#{i}"
                self.key[id(it)] = k
                self.items[k] = it

    def resolve(self, name: str, quals: list[str]) -> Item:
        cands = self.by_name.get(name, [])
        if quals:
            def ancestors(it):
                node = it.parent
                while node is not None:
                    yield node.name
                    node = node.parent
                yield it.record
            cands = [c for c in cands if all(q in set(ancestors(c)) for q in quals)]
        if not cands:
            raise Unsupported(f"unknown data item {name}{' OF ' + ' OF '.join(quals) if quals else ''}")
        if len(cands) > 1:
            raise Unsupported(f"{name} is defined more than once; qualify it with OF")
        return cands[0]

    def resolve_cond(self, name: str, quals: list[str]) -> str:
        """The key of a condition name, qualified by its item and the item's groups when the name is not unique."""
        cands = self.cond_items.get(name, [])
        if quals:
            def ancestors(it):
                node = it
                while node is not None:
                    yield node.name
                    node = node.parent
                yield it.record
            cands = [c for c in cands if all(q in set(ancestors(c[0])) for q in quals)]
        if not cands:
            raise Unsupported(f"unknown condition name {name}{' OF ' + ' OF '.join(quals) if quals else ''}")
        if len(cands) > 1:
            raise Unsupported(f"the condition name {name} is defined more than once; qualify it with OF")
        return cands[0][2]


# DEBUG-ITEM as GnuCOBOL 3.1.2 lays it out (measured: 86 bytes, DEBUG-NAME and DEBUG-CONTENTS 30 each)
DEBUG_ITEM = [(0, s) for s in (
    "01 DEBUG-ITEM", "05 DEBUG-LINE PIC X(6)", "05 FILLER PIC X", "05 DEBUG-NAME PIC X(30)", "05 FILLER PIC X",
    "05 DEBUG-SUB-1 PIC S9(4) SIGN LEADING SEPARATE", "05 FILLER PIC X", "05 DEBUG-SUB-2 PIC S9(4) SIGN LEADING SEPARATE",
    "05 FILLER PIC X", "05 DEBUG-SUB-3 PIC S9(4) SIGN LEADING SEPARATE", "05 FILLER PIC X", "05 DEBUG-CONTENTS PIC X(30)")]


def build_names(model: ProgramModel) -> tuple[Names, dict[str, int]]:
    names = Names()
    names.comma = model.decimal_comma  # DECIMAL-POINT IS COMMA
    sp = getattr(model, "special", None)
    if sp is not None:
        names.classes, names.switch_conds, names.switch_names = dict(sp.classes), dict(sp.switch_conds), dict(sp.switch_names)
        names.symbolic, names.devices = dict(sp.symbolic), dict(sp.devices)
        names.alphabets = dict(getattr(sp, "alphabets", {}))
    records: dict[str, int] = {}
    shared: dict[int, str] = {}  # SAME RECORD AREA group: the buffer its files share
    for f in model.files:
        if not f.records:
            continue
        buffer = shared.setdefault(f.same_record, f.records[0].name) if f.same_record else f.records[0].name
        records[buffer] = max(records.get(buffer, 0), f.size)
        names.file_buffer[f.name] = buffer
        names.files[f.name] = f
        for r in f.records:
            for it in [*walk(r), *r.renames]:  # level 66 RENAMES are names in the record too
                names.add(it, buffer)
    for f in model.files:  # LINAGE-COUNTER: one 4-byte counter for each file with a LINAGE clause
        if f.linage:
            holder = Item(f.name, 1, kind="group")  # so that LINAGE-COUNTER OF file finds it
            counter = Item("LINAGE-COUNTER", 1, kind="num", usage="native", digits=9, signed=False, size=4, offset=0)
            counter.parent = holder
            records[f"_LC_{f.name}"] = 4
            names.add(counter, f"_LC_{f.name}")
            names.linage_items[f.name] = counter
    for r in model.linkage_records:  # storage that belongs to the caller; CALL points it at the caller's data
        records[r.name] = max(r.size, 1)
        for it in [*walk(r), *r.renames]:  # level 66 RENAMES are names in the record too
            names.add(it, r.name)
    for r in model.ws_records:
        buffer = r.name
        if r.redefines and r.redefines in records:  # 01 B REDEFINES A: B is another view of A's storage
            buffer = r.redefines
            while buffer in names.by_name and names.by_name[buffer][0].record != buffer:
                buffer = names.by_name[buffer][0].record
        records[buffer] = max(records.get(buffer, 0), r.size, 1)
        for it in [*walk(r), *r.renames]:  # level 66 RENAMES are names in the record too
            names.add(it, buffer)
    special = Item("RETURN-CODE", 1, kind="num", usage="binary", digits=9, signed=True, size=4)
    records["_SPECIAL"] = 10
    names.add(special, "_SPECIAL")
    tally = Item("TALLY", 1, kind="num", usage="native", digits=5, signed=False, size=2, offset=4)
    names.add(tally, "_SPECIAL")
    sort_return = Item("SORT-RETURN", 1, kind="num", usage="binary", digits=9, signed=True, size=4, offset=6)
    names.add(sort_return, "_SPECIAL")
    if "DEBUG-ITEM" not in names.by_name:  # the special register USE FOR DEBUGGING procedures read
        debug = parse_entries(DEBUG_ITEM)[0]
        records["DEBUG-ITEM"] = debug.size
        for it in walk(debug):
            names.add(it, "DEBUG-ITEM")
    names.finish()
    found: dict[str, list] = {}
    for it in names.items.values():
        k = names.key[id(it)]
        for cname, choices in it.conds:
            found.setdefault(cname, []).append((it, k, choices, it.cond_false.get(cname)))
        for ix in it.indexes:
            names.indexes[ix] = k
    for cname, entries in found.items():
        for it, k, choices, false in entries:
            ck = cname if len(entries) == 1 else f"{cname}@{k}"
            names.conds[ck] = (k, choices, false)
            names.cond_items.setdefault(cname, []).append((it, k, ck))
    return names, records


# ---------------------------------------------------------------- parser

@dataclass
class Node:
    kind: str
    line: int
    data: dict = field(default_factory=dict)


@dataclass
class RefX:
    """A parsed data reference: Python for the Ref, and the item it points at."""
    py: str
    item: Item
    simple: bool  # no subscripts and no reference modification
    key: str

    @property
    def target(self) -> str:
        return f'"{self.key}"' if self.simple else self.py

    @property
    def num(self) -> str:
        return f'S.n("{self.key}")' if self.simple else f"S.n({self.py})"


class Parser:
    def __init__(self, toks: list[Tok], names: Names, paragraphs: set[str], section: str | None = None,
                 owner: dict | None = None, para: str | None = None, altered: set[str] | None = None):
        self.t, self.i, self.names, self.paras = toks, 0, names, paragraphs
        self.section, self.owner = section, owner or {}
        self.para, self.altered = para, altered or set()  # this paragraph, and the paragraphs some ALTER re-points
        self._last = None
        self.comma = getattr(names, "comma", False)

    # -- token helpers
    def peek(self, k: int = 0) -> Tok:
        j = self.i + k
        return self.t[j] if j < len(self.t) else Tok("end", ".", self.t[-1].line if self.t else 0)

    def word(self, k: int = 0) -> str:
        tok = self.peek(k)
        return tok.value if tok.kind == "word" else ""

    def is_op(self, v: str, k: int = 0) -> bool:
        tok = self.peek(k)
        return tok.kind == "op" and tok.value == v

    def take(self) -> Tok:
        tok = self.peek()
        self.i += 1
        return tok

    def accept(self, *words: str) -> bool:
        if self.word() in words:
            self.i += 1
            return True
        return False

    def expect(self, *words: str) -> None:
        if not self.accept(*words):
            raise Unsupported(f"expected {' or '.join(words)} near {self.peek().value!r}")

    def at_boundary(self, stop: set[str]) -> bool:
        tok = self.peek()
        return tok.kind == "end" or (tok.kind == "word" and (tok.value in VERBS or tok.value in stop or tok.value in ENDERS))

    # -- data references
    def is_data(self, k: int = 0) -> bool:
        tok = self.peek(k)
        return tok.kind == "word" and tok.value in self.names.by_name and tok.value not in self.names.cond_items

    def ref(self) -> RefX:
        tok = self.peek()
        if tok.kind != "word" or tok.value not in self.names.by_name:
            if tok.kind == "word" and tok.value in self.names.indexes:
                raise Unsupported(f"{tok.value} is an index name, not a data item")
            raise Unsupported(f"expected a data name near {tok.value!r}")
        self.i += 1
        quals = []
        while self.word() in ("OF", "IN") and self.peek(1).kind == "word":
            self.i += 1
            quals.append(self.take().value)
        # WRITE rec IN file: the file qualifies the record; LINAGE-COUNTER OF file is a name qualified by its file
        quals = [q for q in quals if q not in self.names.files or q in self.names.by_name
                 or any(getattr(c.parent, "name", None) == q for c in self.names.by_name.get(tok.value, []))]
        item = self.names.resolve(tok.value, quals)
        if item.record == "DEBUG-ITEM" and self.section not in self.names.debug_sections:
            raise Unsupported("DEBUG-ITEM outside a USE FOR DEBUGGING procedure: GnuCOBOL updates it as the program "
                              "runs, Séance does not")
        key = self.names.key[id(item)]
        py = f'S.r("{key}"'
        simple = True
        if self.is_op("(") and item.dims():
            self.i += 1
            subs = []
            while not self.is_op(")"):
                if self.peek().kind == "end":
                    raise Unsupported("unclosed subscript")
                if self.word() == "ALL" and getattr(self, "_all_ok", False):  # FUNCTION SUM(TABLE(ALL))
                    self.i += 1
                    subs.append("None")
                    continue
                subs.append(self.subscript())
            self.i += 1
            if "None" in subs:
                return RefX(f'S.all_of("{key}", [{", ".join(subs)}])', item, False, key)
            py += ", " + ", ".join(subs)
            simple = False
        py += ")"
        if self.is_op("(") and self._refmod_ahead():
            self.i += 1
            start = self.expr()
            if not self.is_op(":"):
                raise Unsupported("expected : in reference modification")
            self.i += 1
            length = None if self.is_op(")") else self.expr()
            if not self.is_op(")"):
                raise Unsupported("unclosed reference modification")
            self.i += 1
            py += f".sub({start}{', ' + length if length else ''})"
            simple = False
        elif self.is_op("(") and not item.dims():
            raise Unsupported(f"{tok.value} is not a table, so it cannot have a subscript")
        return RefX(py, item, simple, key)

    def _refmod_ahead(self) -> bool:
        depth, j = 0, self.i
        while j < len(self.t):
            tok = self.t[j]
            if tok.kind == "op" and tok.value == "(":
                depth += 1
            elif tok.kind == "op" and tok.value == ")":
                depth -= 1
                if depth == 0:
                    return False
            elif tok.kind == "op" and tok.value == ":" and depth == 1:
                return True
            elif tok.kind == "end":
                return False
            j += 1
        return False

    def subscript(self) -> str:
        tok = self.peek()
        if tok.kind == "word" and tok.value in self.names.indexes:
            self.i += 1
            base = f'S.idx_value("{tok.value}")'
            if self.peek().kind == "op" and self.peek().value in "+-" and self.peek(1).kind == "num":
                op = self.take().value
                return f"{base} {op} {self.take().value}"
            return base
        return f"int({self.expr()})"

    # -- literal and value operands
    def literal(self) -> str | None:
        tok = self.peek()
        if tok.kind == "word" and tok.value in self.names.symbolic:
            self.i += 1
            return repr(self.names.symbolic[tok.value])
        if tok.kind == "word" and tok.value == "ALL" and self.peek(1).kind in ("str",):
            self.i += 2
            return f"ALL({self.t[self.i - 1].value!r})"
        if tok.kind == "word" and tok.value == "ALL" and self.peek(1).kind == "word" and self.peek(1).value in FIGURATIVE:
            self.i += 2
            return FIGURATIVE[self.t[self.i - 1].value]
        if tok.kind == "word" and tok.value in FIGURATIVE:
            self.i += 1
            return FIGURATIVE[tok.value]
        if tok.kind == "str":
            self.i += 1
            parts = [tok.value]
            while self.is_op("&") and self.peek(1).kind == "str":
                self.i += 2
                parts.append(self.t[self.i - 1].value)
            return repr("".join(parts))
        if tok.kind == "num":
            self.i += 1
            if re.fullmatch(r"0\d+", tok.value):  # 007 compared with text is "007": keep the zeros as written
                return f'Lit("{tok.value}")'
            return f'D("{tok.value}")'
        if tok.kind == "op" and tok.value in "+-" and self.peek(1).kind == "num":
            self.i += 2
            return f'D("{tok.value}{self.t[self.i - 1].value}")'
        return None

    def value(self) -> str:
        """A MOVE source, DISPLAY item or comparison operand: a literal, a figurative constant, a function or a Ref."""
        lit = self.literal()
        if lit is not None:
            return lit
        if self.word() == "FUNCTION":
            return self.function()
        if self.word() in self.names.indexes:
            return f'D(S.idx_value("{self.take().value}"))'
        if self.word() in ("RETURN-CODE", "TALLY"):
            return f'S.r("{self.take().value}")'
        if self.word() == "LENGTH" and self.word(1) == "OF":
            self.i += 2
            return f"D(S.length_of({self.ref().py}))"
        return self.ref().py

    def function(self) -> str:
        """FUNCTION name(args): S.fn gives the result as a field, with the attributes libcob gives it (seance.intrinsics)."""
        self.expect("FUNCTION")
        name = self.take().value
        from .intrinsics import NAMES

        if name not in NAMES:
            raise Unsupported(f"FUNCTION {name} is not supported yet")
        args, where = [], ""
        if name in ("LENGTH", "BYTE-LENGTH") and self.is_op("("):
            folded = self._constant_length()
            if folded is not None:
                return folded
        if self.is_op("(") and not self._refmod_ahead():  # FUNCTION CURRENT-DATE (1:8) is a substring, not arguments
            self.i += 1
            while not self.is_op(")"):
                if self.peek().kind == "end":
                    raise Unsupported("unclosed function arguments")
                if self.word() in ("LEADING", "TRAILING") and name == "TRIM":
                    where = self.take().value
                    continue
                args.append(self._fn_arg())
            self.i += 1
        call = f'S.fn("{name}"' + "".join(", " + a for a in args) + (f', where="{where}"' if where else "") + ")"
        if self.is_op("(") and self._refmod_ahead():
            self.i += 1
            start = self.expr()
            self.i += 1  # ':'
            length = None if self.is_op(")") else self.expr()
            self.i += 1
            call = f"{call}.sub({start}{', ' + length if length else ''})"
        return call

    def _constant_length(self) -> str | None:
        """FUNCTION LENGTH of a literal or of a fixed-size item is a number cobc works out when it compiles: a
        numeric literal, which DISPLAY shows without leading zeros. Anything else is left to the run."""
        save = self.i
        self.i += 1
        tok = self.peek()
        size = None
        if tok.kind == "str" and self.peek(1).kind == "op" and self.peek(1).value == ")":
            size = len(tok.value.encode("latin-1", errors="replace"))
            self.i += 1
        elif self.is_data():
            r = self.ref()
            fixed = ".sub(" not in r.py and not any(getattr(x, "depending", None) for x in _walk_up(r.item))
            if fixed and self.is_op(")"):
                size = r.item.size
        if size is None or not self.is_op(")"):
            self.i = save
            return None
        self.i += 1
        return f'D("{size}")'

    def _fn_arg(self) -> str:
        """One function argument: a field when it is one (a data item, a literal, another function), else the
        value of an arithmetic expression. TABLE(ALL) gives every occurrence."""
        save = self.i
        if self.word() == "FUNCTION":
            out = self.function()
        elif self.is_data():
            self._all_ok = True
            try:
                r = self.ref()
            finally:
                self._all_ok = False
            out = r.py
        else:
            out = self.literal()
        nxt = self.peek()
        if out is None or (nxt.kind == "op" and nxt.value in ("+", "-", "*", "/", "**") and not out.startswith("*")):
            self.i = save
            return self.expr()
        return out

    def _text_arg(self) -> str:
        lit = self.literal()
        if lit is not None:
            return lit if not lit.startswith("D(") else f"str({lit})"
        if self.word() == "FUNCTION":
            return self.function()
        r = self.ref()
        return f"S.text({r.py})"

    # -- arithmetic
    def expr(self) -> str:
        left = self.term()
        while self.peek().kind == "op" and self.peek().value in ("+", "-"):
            op = self.take().value
            left = f"{left} {op} {self.term()}"
        return left

    def term(self) -> str:
        left = self.factor()
        while self.peek().kind == "op" and self.peek().value in ("*", "/"):
            op = self.take().value
            left = f"{left} {op} {self.factor()}"
        return left

    def factor(self) -> str:
        base = self.unary()
        if self.is_op("**"):
            self.i += 1
            return f"{base} ** {self.factor()}"
        return base

    def unary(self) -> str:
        tok = self.peek()
        if tok.kind == "op" and tok.value in ("+", "-"):
            self.i += 1
            return f"({tok.value}{self.unary()})"
        if self.is_op("("):
            self.i += 1
            inner = self.expr()
            if not self.is_op(")"):
                raise Unsupported("unbalanced parentheses")
            self.i += 1
            return f"({inner})"
        return self.operand_num()

    def operand_num(self) -> str:
        tok = self.peek()
        if tok.kind == "op" and tok.value in ("+", "-") and self.peek(1).kind == "num":  # a signed literal: BY -1
            self.i += 2
            return f'D("{tok.value if tok.value == "-" else ""}{self.t[self.i - 1].value}")'
        if tok.kind == "num":
            self.i += 1
            return f'D("{tok.value}")'
        if tok.kind == "word" and tok.value in ("ZERO", "ZEROS", "ZEROES"):
            self.i += 1
            return 'D("0")'
        if tok.kind == "word" and tok.value == "FUNCTION":
            call = self.function()
            return call if call.startswith("D(") else f"S.n({call})"  # LENGTH of a fixed item is a literal already
        if tok.kind == "word" and tok.value in self.names.indexes:
            self.i += 1
            return f'D(S.idx_value("{tok.value}"))'
        if tok.kind == "word" and tok.value in ("RETURN-CODE", "TALLY"):
            self.i += 1
            return f'S.n("{tok.value}")'
        if tok.kind == "word" and tok.value == "LENGTH" and self.word(1) == "OF":
            self.i += 2
            return f"D(S.length_of({self.ref().py}))"
        if tok.kind == "str":
            raise Unsupported(f"a text literal {tok.value!r} where a number is needed")
        return self.ref().num

    # -- conditions
    def relop(self):
        save = self.i
        self.accept("IS")
        negate = self.accept("NOT")
        tok = self.peek()
        op = None
        if tok.kind == "op" and tok.value in ("=", ">", "<", ">=", "<=", "<>"):
            self.i += 1
            op = {"=": "==", "<>": "!="}.get(tok.value, tok.value)
        elif self.accept("EQUAL"):
            self.accept("TO")
            op = "=="
        elif self.accept("GREATER"):
            self.accept("THAN")
            op = ">"
            if self.accept("OR"):
                self.expect("EQUAL")
                self.accept("TO")
                op = ">="
        elif self.accept("LESS"):
            self.accept("THAN")
            op = "<"
            if self.accept("OR"):
                self.expect("EQUAL")
                self.accept("TO")
                op = "<="
        if op is None:
            self.i = save
            return None
        if negate:
            op = {"==": "!=", "!=": "==", ">": "<=", "<": ">=", ">=": "<", "<=": ">"}[op]
        return op

    def relop_ahead(self, k: int) -> bool:
        tok = self.peek(k)
        return (tok.kind == "op" and tok.value in ("=", ">", "<", ">=", "<=", "<>")) or (tok.kind == "word" and tok.value in ("EQUAL", "GREATER", "LESS"))

    def comparand(self) -> str:
        """Operand of a relation. A plain value keeps its type (text or number); arithmetic becomes a number."""
        save = self.i
        try:
            v = self.value()
        except Unsupported:
            self.i = save
            return self.expr()
        if self.peek().kind == "op" and self.peek().value in ("+", "-", "*", "/", "**") and not (self.peek().value in "+-" and self.peek(1).kind == "end"):
            self.i = save
            return self.expr()
        return v

    def condition(self) -> str:
        self._last = None
        return self.cond_or()

    def cond_or(self) -> str:
        parts = [self.cond_and()]
        while self.accept("OR"):
            parts.append(self.cond_and())
        return " or ".join(parts) if len(parts) > 1 else parts[0]

    def cond_and(self) -> str:
        parts = [self.cond_not()]
        while self.accept("AND"):
            parts.append(self.cond_not())
        return " and ".join(f"({p})" if " or " in p else p for p in parts) if len(parts) > 1 else parts[0]

    def cond_not(self) -> str:
        if self.word() == "NOT" and not self.relop_ahead(1) and self.word(1) not in ("POSITIVE", "NEGATIVE", "ZERO", "NUMERIC", "ALPHABETIC"):
            self.i += 1
            return f"not ({self.cond_not()})"
        return self.cond_primary()

    CLASS_WORDS = ("POSITIVE", "NEGATIVE", "ZERO", "NUMERIC", "ALPHABETIC", "ALPHABETIC-UPPER", "ALPHABETIC-LOWER")

    def _continues_relation(self) -> bool:
        """After an operand: does a relational operator or a class test follow (so the operand is a subject)?"""
        k = 1 if self.word() == "IS" else 0
        if self.word(k) == "NOT":
            k += 1
        return self.relop_ahead(k) or self.word(k) in self.CLASS_WORDS or self.word(k) in self.names.classes

    def cond_primary(self) -> str:
        k = 1 if self.word() == "IS" else 0
        if self._last and (self.relop_ahead(k) or (self.word(k) == "NOT" and self.relop_ahead(k + 1))):
            subject = self._last[0]  # A > B AND IS NOT LESS THAN C: the subject is A again
            op = self.relop()
            obj = self.comparand()
            self._last = (subject, op)
            return f'S.cmp({subject}, "{op}", {obj})'
        tok = self.peek()
        if tok.kind == "word" and tok.value in self.names.switch_conds:
            self.i += 1
            n, on = self.names.switch_conds[tok.value]
            return f"S.switch({n})" if on else f"not S.switch({n})"
        if self._last and not (tok.kind == "word" and (tok.value in self.names.cond_items or tok.value in self.names.switch_conds)):
            # A = 1 OR 2, A > B AND C, A = B OR -11 + D: an object alone takes the subject and operator before it
            save = self.i
            try:
                obj = self.comparand()
                if not self._continues_relation() and not (self.peek().kind == "op" and self.peek().value not in (")",)):
                    subject, op = self._last
                    return f'S.cmp({subject}, "{op}", {obj})'
            except Unsupported:
                pass
            self.i = save
        if tok.kind == "word" and tok.value in self.names.cond_items:
            ck = self.cond_name()
            subs = ""
            if self.is_op("("):
                self.i += 1
                parts = []
                while not self.is_op(")"):
                    parts.append(self.subscript())
                self.i += 1
                subs = ", " + ", ".join(parts)
            return f'S.cond("{ck}"{subs})'
        if self.is_op("("):
            save = self.i
            try:
                return self.relation()
            except Unsupported:
                self.i = save + 1
                inner = self.cond_or()
                if not self.is_op(")"):
                    raise Unsupported("unbalanced parentheses in condition")
                self.i += 1
                return f"({inner})"
        if self._last and not self.relop_ahead(0) and (tok.kind in ("num", "str") or (tok.kind == "word" and tok.value in FIGURATIVE)):
            subject, op = self._last
            return f'S.cmp({subject}, "{op}", {self.comparand()})'
        return self.relation()

    def relation(self) -> str:
        subject = self.comparand()
        save = self.i
        self.accept("IS")
        negate = self.accept("NOT")
        cls = self.word()
        if cls in self.names.classes or cls in ("ALPHABETIC-UPPER", "ALPHABETIC-LOWER"):
            self.i += 1
            chars = self.names.classes.get(cls) or ("ABCDEFGHIJKLMNOPQRSTUVWXYZ " if cls == "ALPHABETIC-UPPER" else "abcdefghijklmnopqrstuvwxyz ")
            test = f"S.in_class({subject}, {chars!r})"
            return f"not ({test})" if negate else test
        if cls in ("POSITIVE", "NEGATIVE", "ZERO", "NUMERIC", "ALPHABETIC"):
            self.i += 1
            num = f"S.n({subject})" if subject.startswith("S.r(") else subject
            test = {"POSITIVE": f"{num} > 0", "NEGATIVE": f"{num} < 0", "ZERO": f"{num} == 0",
                    "NUMERIC": f"S.is_numeric({subject})", "ALPHABETIC": f"S.is_alphabetic({subject})"}[cls]
            return f"not ({test})" if negate else test
        self.i = save
        op = self.relop()
        if op is None:
            raise Unsupported(f"expected a comparison near {self.peek().value!r}")
        obj = self.comparand()
        self._last = (subject, op)
        return f'S.cmp({subject}, "{op}", {obj})'

    # -- statement blocks
    def block(self, stop: set[str]) -> list[Node]:
        nodes: list[Node] = []
        while True:
            tok = self.peek()
            if tok.kind == "end" or (tok.kind == "word" and (tok.value in stop or tok.value in ENDERS)):
                return nodes
            start = self.i
            try:
                if tok.kind == "word" and tok.value in VERBS:
                    nodes.append(self.statement(stop))
                else:
                    raise Unsupported(f"unexpected {tok.value!r}")
            except Unsupported as exc:
                self.i = start + 1
                if tok.value == "EXEC":
                    while self.i < len(self.t) and self.word() != "END-EXEC" and self.peek().kind != "end":
                        self.i += 1
                    self.accept("END-EXEC")
                else:
                    while not self.at_boundary(stop):
                        self.i += 1
                text = " ".join(t.raw or t.value for t in self.t[start:self.i])
                nodes.append(Node("unsupported", tok.line, {"text": text, "why": str(exc) or "not supported yet"}))

    def statement(self, stop: set[str]) -> Node:
        tok = self.take()
        handler = getattr(self, "s_" + tok.value.replace("-", "_"), None)
        if handler is None:
            raise Unsupported({"GO": "GO TO", "EXEC": "EXEC (SQL or CICS)"}.get(tok.value, tok.value) + " is not supported yet")
        node = handler(tok.line, stop)
        return node

    def code(self, line: int, py: str) -> Node:
        return Node("code", line, {"py": py})

    def size_phrases(self, stop, end_word, first="SIZE", second="ERROR", on_word="ON"):
        on_err = not_err = None
        inner = stop | {"NOT", end_word}
        if self.word() in (on_word, first) and (self.word() == first or self.word(1) == first):
            self.accept(on_word)
            self.expect(first)
            if second:
                self.expect(second)
            on_err = self.block(inner)
        if self.word() == "NOT" and self.word(1) in (on_word, first):
            self.i += 1
            self.accept(on_word)
            self.expect(first)
            if second:
                self.expect(second)
            not_err = self.block(inner)
        self.accept(end_word)
        return on_err, not_err

    def guarded(self, line, call, on_err, not_err) -> Node:
        if on_err is None and not_err is None:
            return self.code(line, call)
        return Node("guarded", line, {"call": call, "on_err": on_err or [], "not_err": not_err or []})

    def targets(self, allow_rounded=True) -> list[tuple[RefX, bool | str]]:
        out = []
        while self.is_data():
            r = self.ref()
            rounded: bool | str = allow_rounded and self.accept("ROUNDED")
            if rounded and self.accept("MODE"):  # ROUNDED MODE [IS] AWAY-FROM-ZERO and the others
                self.accept("IS")
                mode = self.take().value
                if mode not in ROUND_MODES:
                    raise Unsupported(f"ROUNDED MODE {mode} is not supported yet")
                rounded = mode
            out.append((r, rounded))
        if not out:
            raise Unsupported(f"expected a receiving field near {self.peek().value!r}")
        return out

    def specs(self, items) -> str:
        return "[" + ", ".join(f"({r.target}, lambda: {e}, {rounded!r})" for r, e, rounded in items) + "]"

    # MOVE / INITIALIZE / SET ------------------------------------------------
    def corresponding(self, a: RefX, b: RefX, numeric: bool) -> list[tuple[RefX, RefX]]:
        """The CORRESPONDING pairs of two groups: same name, same groups in between, no FILLER, REDEFINES or OCCURS
        on the way down. For MOVE one of each pair may be a group; for ADD and SUBTRACT both are numbers."""
        def below(root):
            def visit(it, path):
                for c in it.children:
                    if c.name.startswith("FILLER#") or c.redefines or c.occurs or c.level in (66, 88):
                        continue
                    p = path + (c.name,)
                    yield p, c
                    if c.children:
                        yield from visit(c, p)
            yield from visit(root, ())

        if not a.item.children or not b.item.children:
            raise Unsupported("CORRESPONDING needs two groups")
        theirs = dict(below(b.item))
        subs_a = a.py[len(f'S.r("{a.key}"'):-1] if not a.simple else ""
        subs_b = b.py[len(f'S.r("{b.key}"'):-1] if not b.simple else ""
        if ".sub(" in a.py or ".sub(" in b.py:
            raise Unsupported("CORRESPONDING with reference modification")
        pairs = []
        for path, x in below(a.item):
            y = theirs.get(path)
            if y is None:
                continue
            if numeric:
                if x.children or y.children or x.kind not in ("num", "edited") or y.kind not in ("num", "edited"):
                    continue
            elif x.children and y.children:
                continue  # two groups: their own items pair up further down
            kx, ky = self.names.key[id(x)], self.names.key[id(y)]
            pairs.append((RefX(f'S.r("{kx}"{subs_a})', x, not subs_a, kx), RefX(f'S.r("{ky}"{subs_b})', y, not subs_b, ky)))
        return pairs

    def s_MOVE(self, line, stop):
        if self.accept("CORRESPONDING", "CORR"):
            a = self.ref()
            self.expect("TO")
            outs = []
            for r, _ in self.targets(allow_rounded=False):
                outs += [f"S.move({x.py}, {y.target})" for x, y in self.corresponding(a, r, numeric=False)]
            return self.code(line, "; ".join(outs) or "pass  # MOVE CORRESPONDING: no items correspond")
        src = self.value()
        self.expect("TO")
        names = [r.target for r, _ in self.targets(allow_rounded=False)]
        return self.code(line, f"S.move({src}, {', '.join(names)})")

    INIT_CATEGORIES = ("ALPHABETIC", "ALPHANUMERIC", "NUMERIC", "ALPHANUMERIC-EDITED", "NUMERIC-EDITED", "NATIONAL", "NATIONAL-EDITED")

    def s_INITIALIZE(self, line, stop):
        names = [r.target for r, _ in self.targets(allow_rounded=False)]
        opts = []
        if self.accept("WITH"):
            self.expect("FILLER")
            opts.append("filler=True")
        if self.word() == "ALL" or (self.word() in self.INIT_CATEGORIES and self.word(1) == "TO"):
            cat = self.take().value
            self.expect("TO")
            self.expect("VALUE")
            opts.append(f"to_value={cat!r}")
        self.accept("THEN")
        if self.accept("REPLACING"):
            reps = []
            while self.word() in self.INIT_CATEGORIES:
                cat = self.take().value
                self.accept("DATA")
                self.expect("BY")
                reps.append(f"({cat!r}, {self.value()})")
            if not reps:
                raise Unsupported("expected a category after REPLACING")
            opts.append(f"replacing=[{', '.join(reps)}]")
        self.accept("THEN")
        if self.word() == "TO" and self.word(1) == "DEFAULT":
            self.i += 2
            opts.append("default=True")
        self.accept("END-INITIALIZE")
        return self.code(line, f"S.initialize({', '.join(names + opts)})")

    def cond_name(self) -> str:
        """A condition name with its qualifiers (A OF REC), as the key the runtime knows it by."""
        name = self.take().value
        quals = []
        while self.word() in ("OF", "IN") and self.peek(1).kind == "word":
            self.i += 1
            quals.append(self.take().value)
        return self.names.resolve_cond(name, quals)

    def s_SET(self, line, stop):
        if self.word() in self.names.cond_items:
            calls = []
            while self.word() in self.names.cond_items:
                ck = self.cond_name()
                subs = ""
                if self.is_op("("):
                    self.i += 1
                    parts = []
                    while not self.is_op(")"):
                        parts.append(self.subscript())
                    self.i += 1
                    subs = ", " + ", ".join(parts)
                calls.append((ck, subs))
            self.expect("TO")
            if self.accept("TRUE"):
                return self.code(line, "; ".join(f'S.set_true("{ck}"{subs})' for ck, subs in calls))
            self.expect("FALSE")
            for ck, _ in calls:
                if self.names.conds[ck][2] is None:
                    raise Unsupported(f"SET {ck.split('@')[0]} TO FALSE: its 88 level has no FALSE value")
            return self.code(line, "; ".join(f'S.set_false("{ck}"{subs})' for ck, subs in calls))
        if self.word() in self.names.switch_names:
            calls = []
            while self.word() in self.names.switch_names:
                n = self.names.switch_names[self.take().value]
                self.expect("TO")
                on = self.accept("ON")
                if not on:
                    self.expect("OFF")
                calls.append(f"S.set_switch({n}, {on})")
            return self.code(line, "; ".join(calls))
        tgts = []
        while self.word() in self.names.indexes or self.is_data():
            if self.word() in self.names.indexes:
                tgts.append(("idx", self.take().value))
            else:
                tgts.append(("data", self.ref()))
        if not tgts:
            raise Unsupported("expected an index or data name after SET")
        if self.accept("UP", "DOWN"):
            sign = "+" if self.t[self.i - 1].value == "UP" else "-"
            self.expect("BY")
            amount = self.operand_num()
            return self.code(line, "; ".join(f'S.set_index("{n}", S.idx_value("{n}") {sign} int({amount}))' for k, n in tgts if k == "idx"))
        self.expect("TO")
        if self.word() in self.names.indexes:
            src = f'S.idx_value("{self.take().value}")'
        else:
            src = f"int({self.operand_num()})"
        out = []
        for k, n in tgts:
            out.append(f'S.set_index("{n}", {src})' if k == "idx" else f"S.move(D({src}), {n.target})")
        return self.code(line, "; ".join(out))

    # arithmetic --------------------------------------------------------------
    def s_COMPUTE(self, line, stop):
        tg = self.targets()
        if self.is_op("="):
            self.i += 1
        elif not self.accept("EQUAL"):
            raise Unsupported("expected = in COMPUTE")
        e = self.expr()
        on_err, not_err = self.size_phrases(stop, "END-COMPUTE")
        guarded = on_err is not None or not_err is not None
        call = f"S.compute({self.specs([(r, e, rd) for r, rd in tg])}, guarded={guarded})"
        return self.guarded(line, call if not guarded else call, on_err, not_err)

    def _operands(self, until: set[str]) -> list[str]:
        out = []
        while self.word() not in until and self.peek().kind != "end":
            out.append(self.operand_num())
        if not out:
            raise Unsupported("expected operands")
        return out

    def _arith(self, line, stop, items, end_word):
        on_err, not_err = self.size_phrases(stop, end_word)
        guarded = on_err is not None or not_err is not None
        return self.guarded(line, f"S.compute({self.specs(items)}, guarded={guarded})", on_err, not_err)

    def s_ADD(self, line, stop):
        if self.accept("CORRESPONDING", "CORR"):
            a = self.ref()
            self.expect("TO")
            b, rounded = self.targets()[0]
            items = [(y, f"{y.num} + {x.num}", rounded) for x, y in self.corresponding(a, b, numeric=True)]
            if not items:
                return self.code(line, "pass  # ADD CORRESPONDING: no items correspond")
            return self._arith(line, stop, items, "END-ADD")
        total = " + ".join(self._operands({"TO", "GIVING"}))
        if self.accept("TO"):
            dests = self.targets()
            if self.accept("GIVING"):
                base = " + ".join([total] + [r.num for r, _ in dests])
                items = [(r, base, rd) for r, rd in self.targets()]
            else:
                items = [(r, f"{r.num} + {total}", rd) for r, rd in dests]
        else:
            self.expect("GIVING")
            items = [(r, total, rd) for r, rd in self.targets()]
        return self._arith(line, stop, items, "END-ADD")

    def s_SUBTRACT(self, line, stop):
        if self.accept("CORRESPONDING", "CORR"):
            a = self.ref()
            self.expect("FROM")
            b, rounded = self.targets()[0]
            items = [(y, f"{y.num} - {x.num}", rounded) for x, y in self.corresponding(a, b, numeric=True)]
            if not items:
                return self.code(line, "pass  # SUBTRACT CORRESPONDING: no items correspond")
            return self._arith(line, stop, items, "END-SUBTRACT")
        total = " + ".join(self._operands({"FROM"}))
        self.expect("FROM")
        if self.is_data():
            dests = self.targets()
        else:
            dests = [(None, False)]
            minuend = self.operand_num()
        if self.accept("GIVING"):
            base = dests[0][0].num if dests[0][0] is not None else minuend
            items = [(r, f"{base} - ({total})", rd) for r, rd in self.targets()]
        else:
            items = [(r, f"{r.num} - ({total})", rd) for r, rd in dests]
        return self._arith(line, stop, items, "END-SUBTRACT")

    def s_MULTIPLY(self, line, stop):
        a = self.operand_num()
        self.expect("BY")
        if self.is_data():
            dests = self.targets()  # MULTIPLY A BY B C: B and C get the products; MULTIPLY A BY B GIVING C: B is an operand
            if self.accept("GIVING"):
                items = [(r, f"{a} * {dests[0][0].num}", rd) for r, rd in self.targets()]
            else:
                items = [(r, f"{a} * {r.num}", rd) for r, rd in dests]
        else:
            b = self.operand_num()
            self.expect("GIVING")
            items = [(r, f"{a} * {b}", rd) for r, rd in self.targets()]
        return self._arith(line, stop, items, "END-MULTIPLY")

    def s_DIVIDE(self, line, stop):
        a = self.operand_num()
        remainder = None
        if self.accept("INTO"):
            if self.is_data():
                dests = self.targets()  # DIVIDE A INTO B C: B and C get the quotients; with GIVING, B is the dividend
                if self.accept("GIVING"):
                    dividend = dests[0][0].num
                    items = [(r, f"{dividend} / {a}", rd) for r, rd in self.targets()]
                    divisor = a
                else:
                    items = [(r, f"{r.num} / {a}", rd) for r, rd in dests]
                    dividend = divisor = None
            else:
                dividend = self.operand_num()
                divisor = a
                self.expect("GIVING")
                items = [(r, f"{dividend} / {a}", rd) for r, rd in self.targets()]
        else:
            self.expect("BY")
            divisor = self.operand_num()
            dividend = a
            self.expect("GIVING")
            items = [(r, f"{a} / {divisor}", rd) for r, rd in self.targets()]
        if self.accept("REMAINDER"):
            if dividend is None:
                raise Unsupported("DIVIDE ... REMAINDER needs GIVING")
            rem = self.ref()
            q = items[0][0]
            remainder = (rem, f"{dividend} - {q.num} * {divisor}")
        node = self._arith(line, stop, items, "END-DIVIDE")
        if remainder:
            extra = f"S.compute([({remainder[0].target}, lambda: {remainder[1]}, False)])"
            if node.kind == "code":
                node.data["py"] += f"; {extra}"
            else:
                node.data["not_err"] = node.data["not_err"] + [self.code(line, extra)]
        return node

    # control flow ------------------------------------------------------------
    def s_IF(self, line, stop):
        cond = self.condition()
        self.accept("THEN")
        then = self.block(stop | {"ELSE", "END-IF"})
        other: list[Node] = []
        if self.accept("ELSE"):
            other = self.block(stop | {"END-IF"})
        self.accept("END-IF")
        return Node("if", line, {"cond": cond, "then": then, "else": other})

    def _subject(self):
        """An EVALUATE subject: TRUE, FALSE, a value, or a condition (EVALUATE X NUMERIC WHEN TRUE)."""
        if self.accept("TRUE"):
            return None
        if self.accept("FALSE"):
            return "FALSE"
        save = self.i
        if not (self.peek().kind == "word" and self.peek().value in self.names.cond_items):
            try:
                v = self.comparand()
                if not self._continues_relation():
                    return v
            except Unsupported:
                pass
        self.i = save
        self._last = None
        return ("cond", self.cond_or())

    def s_EVALUATE(self, line, stop):
        subjects = [self._subject()]
        while self.accept("ALSO"):
            subjects.append(self._subject())
        branches = []
        while self.accept("WHEN"):
            if self.accept("OTHER"):
                body = self.block(stop | {"WHEN", "END-EVALUATE"})
                branches.append((None, body))
                continue
            tests = []
            for k, subject in enumerate(subjects):
                if k:
                    self.expect("ALSO")
                tests.append(self._when_object(subject))
            cond = " and ".join(f"({t})" for t in tests if t != "True") or "True"
            body = self.block(stop | {"WHEN", "END-EVALUATE"})
            branches.append((cond, body))
        self.accept("END-EVALUATE")
        return Node("evaluate", line, {"branches": branches})

    def _when_object(self, subject) -> str:
        if self.accept("ANY"):
            return "True"
        if subject is None:
            self._last = None
            return self.cond_or()
        if subject == "FALSE":
            self._last = None
            return f"not ({self.cond_or()})"
        if isinstance(subject, tuple):  # the subject is a condition: WHEN TRUE, WHEN FALSE or WHEN another condition
            if self.accept("TRUE"):
                return subject[1]
            if self.accept("FALSE"):
                return f"not ({subject[1]})"
            self._last = None
            return f"bool({subject[1]}) == bool({self.cond_or()})"
        negate = self.accept("NOT")
        lo = self.comparand()
        if self.accept("THRU", "THROUGH"):
            hi = self.comparand()
            test = f'S.cmp({subject}, ">=", {lo}) and S.cmp({subject}, "<=", {hi})'
        else:
            test = f'S.cmp({subject}, "==", {lo})'
        return f"not ({test})" if negate else test

    def proc_name(self, k: int = 0) -> str:
        """The token as a procedure name: a word, or digits only (PERFORM 10, a paragraph named 10)."""
        tok = self.peek(k)
        if tok.kind == "word":
            return tok.value
        if tok.kind == "num" and tok.value.isdigit() and self.word(k + 1) != "TIMES":
            return tok.value
        return ""

    def is_para(self, k: int = 0) -> bool:
        name = self.proc_name(k)
        return bool(name) and (name in self.paras or any(p.startswith(name + "@") for p in self.paras))

    def para_ref(self) -> str:
        """A paragraph or section name, with OF/IN SECTION when given: the key it is filed under. Without a
        qualifier, a name used in more than one section means the one in the current section."""
        name = self.take().value
        qual = None
        if self.word() in ("OF", "IN") and self.proc_name(1):
            self.i += 1
            qual = self.take().value
        here = qual or self.section
        if here and f"{name}@{here}" in self.paras:
            return f"{name}@{here}"
        if qual and self.owner.get(name) not in (qual, None):
            raise Unsupported(f"there is no paragraph {name} in section {qual}")
        if name not in self.paras:
            raise Unsupported(f"unknown procedure {name}")
        return name

    def s_PERFORM(self, line, stop):
        if self.is_para():
            target = self.para_ref()
            last = None
            if self.accept("THRU", "THROUGH"):
                last = self.para_ref()
            mode = self.loop_mode()
            call = f'S.perform("{target}"' + (f', "{last}"' if last else "") + ")"
            return Node("loop", line, {"mode": mode, "body": [self.code(line, call)]})
        mode = self.loop_mode()
        body = self.block(stop | {"END-PERFORM"})
        self.expect("END-PERFORM")
        return Node("loop", line, {"mode": mode, "body": body, "inline": True})

    def loop_mode(self):
        if self.accept("FOREVER"):
            return ("forever",)
        if self.word() == "UNTIL" and self.word(1) == "EXIT":
            self.i += 2
            return ("forever",)
        if self.word() == "TEST" or (self.word() == "WITH" and self.word(1) == "TEST"):
            self.accept("WITH")  # WITH is optional: PERFORM P TEST AFTER UNTIL ...
            self.expect("TEST")
            after = self.accept("AFTER")
            if not after:
                self.expect("BEFORE")
            if self.accept("VARYING"):
                return self._varying(after)
            self.expect("UNTIL")
            return ("until", self.condition(), after)
        if self.accept("UNTIL"):
            return ("until", self.condition(), False)
        if self.accept("VARYING"):
            return self._varying(False)
        if (self.peek().kind == "num" or self.is_data()) and self._times_ahead():
            n = self.operand_num()
            self.expect("TIMES")
            return ("times", n)
        return ("once",)

    def _times_ahead(self) -> bool:
        j = self.i + 1
        depth = 0
        while j < len(self.t):
            tok = self.t[j]
            if tok.kind == "op" and tok.value == "(":
                depth += 1
            elif tok.kind == "op" and tok.value == ")":
                depth -= 1
            elif depth == 0:
                return tok.kind == "word" and tok.value == "TIMES"
            j += 1
        return False

    def _varying(self, after: bool):
        levels = []
        while True:
            if self.word() in self.names.indexes:
                var = ("idx", self.take().value)
            else:
                var = ("data", self.ref())
            self.expect("FROM")
            start = self.operand_num()
            self.expect("BY")
            step = self.operand_num()
            self.expect("UNTIL")
            self._last = None
            cond = self.cond_or()
            levels.append((var, start, step, cond))
            if not self.accept("AFTER"):
                break
        return ("varying", levels, after)

    def s_GO(self, line, stop):
        self.accept("TO")
        targets = []
        while self.is_para():
            targets.append(self.para_ref())
        if self.para in self.altered and not self.word() == "DEPENDING":
            # the GO TO of a paragraph an ALTER names goes where the last ALTER pointed it
            return Node("goto", line, {"targets": targets or [None], "alter": self.para})
        if not targets:
            raise Unsupported("GO TO without a paragraph name, in a paragraph no ALTER names")
        if self.accept("DEPENDING"):
            self.accept("ON")
            sel = self.operand_num()
            return Node("goto", line, {"targets": targets, "depending": sel})
        return Node("goto", line, {"targets": targets})

    def s_ALTER(self, line, stop):
        calls = []
        while self.is_para():
            src = self.para_ref()
            self.expect("TO")
            self.accept("PROCEED")
            self.accept("TO")
            calls.append(f'S.alter("{src}", "{self.para_ref()}")')
        if not calls:
            raise Unsupported("expected a paragraph name after ALTER")
        return self.code(line, "; ".join(calls))

    def s_STOP(self, line, stop):
        if self.accept("RUN"):
            return Node("stop", line)
        raise Unsupported("STOP with a literal is not supported")

    def s_GOBACK(self, line, stop):
        return Node("goback", line)

    def s_NEXT(self, line, stop):
        self.expect("SENTENCE")
        return Node("next_sentence", line)

    def s_EXIT(self, line, stop):
        if self.accept("PARAGRAPH"):
            return Node("return", line)
        if self.accept("SECTION"):
            return Node("exit_section", line)
        if self.accept("PROGRAM"):
            return self.code(line, "S.exit_program()  # EXIT PROGRAM")
        if self.accept("PERFORM"):
            if self.accept("CYCLE"):
                return Node("continue", line)
            return Node("break", line)
        return self.code(line, "pass  # EXIT")

    def s_CONTINUE(self, line, stop):
        return self.code(line, "pass  # CONTINUE")

    # files and console -------------------------------------------------------
    def s_OPEN(self, line, stop):
        calls, mode = [], None
        while not self.at_boundary(stop):
            w = self.take().value
            if w in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                mode = {"INPUT": "input", "OUTPUT": "output", "I-O": "io", "EXTEND": "extend"}[w]
            elif w in self.names.files and mode:
                calls.append(f'S.open("{w}", "{mode}")')
            elif w in ("WITH", "NO", "REWIND", "LOCK"):
                continue
            else:
                raise Unsupported(f"unknown file {w} in OPEN")
        return self.code(line, "; ".join(calls) or "pass")

    def s_CLOSE(self, line, stop):
        calls = []
        while not self.at_boundary(stop):
            w = self.take().value
            if w in self.names.files:
                calls.append([w, ""])
            elif calls and w in ("REEL", "UNIT"):
                calls[-1][1] = "reel"  # a disk file stays open and answers 07
            elif calls and w == "REWIND":
                calls[-1][1] = "norewind"  # WITH NO REWIND: closed, and 07
            elif calls and w == "LOCK":
                calls[-1][1] = "lock"  # no OPEN again in this run
        return self.code(line, "; ".join(f'S.close("{w}"' + (f', how="{how}")' if how else ")") for w, how in calls) or "pass")

    def s_READ(self, line, stop):
        file = self.take().value
        if file not in self.names.files:
            raise Unsupported(f"READ of unknown file {file}")
        nxt = bool(self.accept("NEXT"))
        prev = bool(self.accept("PREVIOUS"))
        self.accept("RECORD")
        into = None
        if self.accept("INTO"):
            into = self.ref().target
        at_end = not_at_end = None
        inner = stop | {"NOT", "END-READ"}
        if self.word() in ("AT", "END") and not self.word() == "END-READ":
            self.accept("AT")
            self.expect("END")
            at_end = self.block(inner)
        if self.word() == "NOT" and self.word(1) in ("AT", "END"):
            self.i += 1
            self.accept("AT")
            self.expect("END")
            not_at_end = self.block(inner)
        key = None
        if self.word() == "KEY":
            self.i += 1
            self.accept("IS")
            key = self.ref().key
        inv, not_inv = self.key_phrases(stop, "END-READ")
        if at_end is None and not_at_end is None and self.word() in ("AT", "END") and self.word() != "END-READ":
            self.accept("AT")
            self.expect("END")
            at_end = self.block(inner)
            if self.word() == "NOT" and self.word(1) in ("AT", "END"):
                self.i += 1
                self.accept("AT")
                self.expect("END")
                not_at_end = self.block(inner)
        self.accept("END-READ")
        args = f'"{file}"' + (f", {into}" if into else (", None" if key else "")) + (f', key="{key}"' if key else "")
        call = (f"S.read_next({args}, previous=True)" if prev else f"S.read_next({args})" if nxt else f"S.read({args})")
        fail, ok = (at_end or []) + (inv or []), (not_at_end or []) + (not_inv or [])
        if at_end is None and not_at_end is None and inv is None and not_inv is None:
            return self.code(line, call)
        call = call[:-1] + ", phrase=True)"
        return Node("if", line, {"cond": call, "then": ok, "else": fail})

    def key_phrases(self, stop, end_word):
        """[INVALID KEY statements] [NOT INVALID KEY statements]."""
        inv = not_inv = None
        inner = stop | {"NOT", end_word}
        if self.word() == "INVALID":
            self.i += 1
            self.accept("KEY")
            inv = self.block(inner)
        if self.word() == "NOT" and self.word(1) == "INVALID":
            self.i += 2
            self.accept("KEY")
            not_inv = self.block(inner)
        return inv, not_inv

    def keyed(self, line, call, stop, end_word) -> Node:
        inv, not_inv = self.key_phrases(stop, end_word)
        self.accept(end_word)
        if inv is not None or not_inv is not None:
            call = call[:-1] + ", phrase=True)"
        return self.guarded(line, call, inv, not_inv)

    def s_REWRITE(self, line, stop):
        rec = self.ref()
        src = self.value() if self.accept("FROM") else None
        return self.keyed(line, f'S.rewrite("{rec.key}", {src or "None"})', stop, "END-REWRITE")

    def s_DELETE(self, line, stop):
        if self.accept("FILE"):  # DELETE FILE f ...: the files themselves go
            names = []
            while self.word() in self.names.files:
                names.append(self.take().value)
            if not names:
                raise Unsupported(f"DELETE FILE of unknown file {self.peek().value}")
            node = self.keyed(line, "S.delete_file(" + ", ".join(repr(n) for n in names) + ")", stop, "END-DELETE")
            return node
        file = self.take().value
        if file not in self.names.files:
            raise Unsupported(f"DELETE of unknown file {file}")
        self.accept("RECORD")
        return self.keyed(line, f'S.delete("{file}")', stop, "END-DELETE")

    _START_OPS = [(("=",), "="), (("EQUAL", "TO"), "="), (("EQUAL",), "="), ((">=",), ">="), ((">", "="), ">="),
                  (("GREATER", "THAN", "OR", "EQUAL", "TO"), ">="), (("GREATER", "OR", "EQUAL"), ">="), (("NOT", "<"), ">="),
                  (("NOT", "LESS", "THAN"), ">="), (("NOT", "LESS"), ">="), ((">",), ">"), (("GREATER", "THAN"), ">"),
                  (("GREATER",), ">"), (("<=",), "<="), (("LESS", "THAN", "OR", "EQUAL", "TO"), "<="), (("LESS", "OR", "EQUAL"), "<="),
                  (("NOT", ">"), "<="), (("NOT", "GREATER", "THAN"), "<="), (("NOT", "GREATER"), "<="), (("<",), "<"),
                  (("LESS", "THAN"), "<"), (("LESS",), "<")]

    def s_START(self, line, stop):
        file = self.take().value
        if file not in self.names.files:
            raise Unsupported(f"START of unknown file {file}")
        op, key = ">=", None
        if self.accept("FIRST"):
            op = "first"
        elif self.accept("LAST"):
            op = "last"
        elif self.accept("KEY"):
            self.accept("IS")
            for words, sym in self._START_OPS:
                if all(self.peek(k).value == w for k, w in enumerate(words)):
                    self.i += len(words)
                    op = sym
                    break
            else:
                raise Unsupported("START: cannot read the comparison")
            if op != "=":
                self.accept("TO")  # GREATER OR EQUAL TO, NOT LESS THAN TO ...
            key = self.ref().key
        call = f'S.start("{file}", "{op}"' + (f', "{key}"' if key else "") + ")"
        if op in ("first", "last"):
            call = f'S.start("{file}", "{op}")'
        return self.keyed(line, call, stop, "END-START")

    # CALL -------------------------------------------------------------------
    def s_CALL(self, line, stop):
        tok = self.peek()
        if tok.kind == "str":
            self.i += 1
            target = repr(tok.value.strip().upper())
        elif self.is_data():
            target = self.ref().py
        else:
            raise Unsupported("CALL needs a program name")
        args, mode = [], "reference"
        if self.accept("USING"):
            while True:
                if self.accept("BY"):
                    mode = {"REFERENCE": "reference", "CONTENT": "content", "VALUE": "value"}.get(self.take().value, "reference")
                    continue
                if self.word() in ("REFERENCE", "CONTENT", "VALUE") and self.peek(1).kind != "end":
                    mode = self.take().value.lower()
                    continue
                if self.word() == "LENGTH" and self.word(1) == "OF":
                    self.i += 2
                    args.append(f'("content", D(S.length_of({self.ref().py})))')
                    continue
                if self.word() in ("ADDRESS", "OMITTED"):
                    raise Unsupported(f"CALL ... {self.word()} is not supported yet")
                lit = self.literal()
                if lit is not None:
                    args.append(f'("content", {lit})')
                    continue
                if self.is_data():
                    args.append(f'("{mode}", {self.ref().py})')
                    continue
                break
        returning = None
        if self.accept("RETURNING") or self.accept("GIVING"):
            self.accept("INTO")
            returning = self.ref().target
        exc = not_exc = None
        inner = stop | {"NOT", "END-CALL"}
        if self.word() in ("ON", "EXCEPTION", "OVERFLOW") and (self.word() != "ON" or self.word(1) in ("EXCEPTION", "OVERFLOW")):
            self.accept("ON")
            self.take()
            exc = self.block(inner)
        if self.word() == "NOT" and self.word(1) in ("ON", "EXCEPTION", "OVERFLOW"):
            self.i += 1
            self.accept("ON")
            self.take()
            not_exc = self.block(inner)
        self.accept("END-CALL")
        call = (f"S.call({target}, [{', '.join(args)}]" + (", on_exception=True" if exc is not None or not_exc is not None else "")
                + (f", returning={returning}" if returning else "") + ")")
        return self.guarded(line, call, exc, not_exc)

    def s_CANCEL(self, line, stop):
        calls = []
        while self.peek().kind == "str" or self.is_data():
            calls.append(f"S.cancel({repr(self.take().value.upper()) if self.peek().kind == 'str' else self.ref().py})")
        return self.code(line, "; ".join(calls) or "pass")

    # SORT / MERGE --------------------------------------------------------------
    def _proc_range(self):
        self.accept("PROCEDURE")
        self.accept("IS")
        first = self.para_ref()
        last = None
        if self.accept("THRU") or self.accept("THROUGH"):
            last = self.para_ref()
        return f'("{first}", {repr(last)})'

    def s_SORT(self, line, stop, merge=False):
        target = self.take().value
        keys = []
        while self.word() in ("ON", "ASCENDING", "DESCENDING"):
            self.accept("ON")
            asc = self.take().value == "ASCENDING"
            self.accept("KEY")
            self.accept("IS")
            while self.is_data():
                keys.append(f'({asc}, "{self.ref().key}")')
        if self.accept("WITH") or self.word() == "DUPLICATES":
            self.accept("DUPLICATES")
            self.accept("IN")
            self.accept("ORDER")
        collating = None
        if self.word() in ("COLLATING", "SEQUENCE"):
            self.accept("COLLATING")
            self.expect("SEQUENCE")
            self.accept("FOR")
            self.accept("ALPHANUMERIC")
            self.accept("IS")
            name = self.take().value
            if name not in self.names.alphabets:
                raise Unsupported(f"COLLATING SEQUENCE {name}: no ALPHABET of that name in SPECIAL-NAMES")
            table = self.names.alphabets[name]
            collating = f'bytes.fromhex("{table.hex()}")' if table is not None else "None"
        if target not in self.names.files:
            if target in self.names.by_name:  # SORT of a table in WORKING-STORAGE
                key = self.names.key[id(self.names.resolve(target, []))]
                return self.code(line, f'S.sort_table("{key}", [{", ".join(keys)}])')
            raise Unsupported(f"SORT of unknown file {target}")
        using = giving = inp = outp = None
        if self.accept("USING"):
            using = []
            while self.word() in self.names.files:
                using.append(self.take().value)
        elif self.accept("INPUT"):
            inp = self._proc_range()
        if self.accept("GIVING"):
            giving = []
            while self.word() in self.names.files:
                giving.append(self.take().value)
        elif self.accept("OUTPUT"):
            outp = self._proc_range()
        if (using is None and inp is None) or (giving is None and outp is None):
            raise Unsupported("SORT needs USING or INPUT PROCEDURE, and GIVING or OUTPUT PROCEDURE")
        parts = [f'"{target}"', f'[{", ".join(keys)}]']
        parts.append(f"using={using!r}" if using is not None else f"input_proc={inp}")
        parts.append(f"giving={giving!r}" if giving is not None else f"output_proc={outp}")
        if collating is not None:
            parts.append(f"collating={collating}")  # COLLATING SEQUENCE: instead of the program's
        return self.code(line, f"S.sort({', '.join(parts)})" + ("  # MERGE" if merge else ""))

    def s_MERGE(self, line, stop):
        return self.s_SORT(line, stop, merge=True)

    def s_RELEASE(self, line, stop):
        rec = self.ref()
        src = self.value() if self.accept("FROM") else None
        return self.code(line, f'S.release("{rec.key}", {src or "None"})')

    def s_RETURN(self, line, stop):
        file = self.take().value
        if file not in self.names.files:
            raise Unsupported(f"RETURN of unknown sort file {file}")
        self.accept("RECORD")
        into = self.ref().target if self.accept("INTO") else None
        at_end = not_at_end = None
        inner = stop | {"NOT", "END-RETURN"}
        if self.word() in ("AT", "END") and self.word() != "END-RETURN":
            self.accept("AT")
            self.expect("END")
            at_end = self.block(inner)
        if self.word() == "NOT" and self.word(1) in ("AT", "END"):
            self.i += 1
            self.accept("AT")
            self.expect("END")
            not_at_end = self.block(inner)
        self.accept("END-RETURN")
        call = f'S.return_("{file}"' + (f", {into}" if into else "") + ")"
        if at_end is None and not_at_end is None:
            return self.code(line, call)
        return Node("if", line, {"cond": call, "then": not_at_end or [], "else": at_end or []})

    def s_WRITE(self, line, stop):
        rec = self.ref()
        src = None
        if self.accept("FROM"):
            src = self.value()
        adv = "None"
        if self.word() in ("BEFORE", "AFTER"):
            when = self.take().value.lower()
            self.accept("ADVANCING")
            if self.accept("PAGE"):
                adv = f'("{when}", "page")'
            elif self.peek().kind == "num" or self.is_data():
                n = self.operand_num()
                self.accept("LINE", "LINES")
                adv = f'("{when}", int({n}))'
            else:
                self.take()  # a mnemonic name such as TOP-OF-PAGE
                adv = f'("{when}", "page")'
        eops = ("END-OF-PAGE", "EOP")
        inner = stop | {"NOT", "END-WRITE"}
        eop_blk = not_eop_blk = None
        if self.word() in eops or (self.word() == "AT" and self.word(1) in eops):
            self.accept("AT")
            self.i += 1
            eop_blk = self.block(inner)
        if self.word() == "NOT" and (self.word(1) in eops or (self.word(1) == "AT" and self.word(2) in eops)):
            self.i += 1
            self.accept("AT")
            self.i += 1
            not_eop_blk = self.block(inner)
        if eop_blk is not None or not_eop_blk is not None:
            self.accept("END-WRITE")
            call = f'S.write("{rec.key}", {src or "None"}, {adv}, eop=True)'
            return Node("if", line, {"cond": call, "then": not_eop_blk or [], "else": eop_blk or []})
        return self.keyed(line, f'S.write("{rec.key}", {src or "None"}, {adv})', stop, "END-WRITE")

    def s_DISPLAY(self, line, stop):
        parts = []
        upon, no_adv = "console", False
        while not self.at_boundary(stop):
            if self.accept("UPON"):
                dev = self.take().value
                dev = self.names.devices.get(dev, dev)
                upon = "syserr" if dev in ("SYSERR", "STDERR") else "console"
                continue
            if self.word() == "WITH" or (self.word() == "NO" and self.word(1) == "ADVANCING"):
                self.accept("WITH")
                self.expect("NO")
                self.expect("ADVANCING")
                no_adv = True
                continue
            tok = self.peek()
            if tok.kind == "num" or (tok.kind == "op" and tok.value in "+-" and self.peek(1).kind == "num"):
                text = tok.value if tok.kind == "num" else tok.value + self.peek(1).value
                self.i += 1 if tok.kind == "num" else 2
                parts.append(repr(text.replace(".", ",") if self.comma else text))  # DECIMAL-POINT IS COMMA shows 2,25
                continue
            parts.append(self.value())
        args = ", ".join(parts)
        extra = (f', upon="{upon}"' if upon != "console" else "") + (", no_advancing=True" if no_adv else "")
        self.accept("END-DISPLAY")
        return self.code(line, f"S.display({args}{extra})")

    def s_ACCEPT(self, line, stop):
        target = self.ref().target
        source = "console"
        if self.accept("FROM"):
            w = self.take().value
            if w == "DATE":
                source = "date-yyyymmdd" if self.accept("YYYYMMDD") else "date"
            elif w == "DAY":
                source = "day-yyyyddd" if self.accept("YYYYDDD") else "day"
            elif w == "TIME":
                source = "time"
            elif w == "DAY-OF-WEEK":
                source = "day-of-week"
            elif w in ("CONSOLE", "SYSIN", "STDIN", "SYSIPT") or self.names.devices.get(w) in ("CONSOLE", "SYSIN", "STDIN", "SYSIPT"):
                source = "console"
            else:
                raise Unsupported(f"ACCEPT FROM {w} is not supported yet")
        self.accept("END-ACCEPT")
        return self.code(line, f'S.accept({target}, "{source}")')

    # string verbs ------------------------------------------------------------
    def s_STRING(self, line, stop):
        parts, pending = [], []
        while not self.word() == "INTO":
            if self.accept("DELIMITED"):
                self.accept("BY")
                delim = "None" if self.accept("SIZE") else self.value()
                parts += [f"({v}, {delim})" for v in pending]
                pending = []
            else:
                if self.peek().kind == "end":
                    raise Unsupported("STRING without INTO")
                pending.append(self.value())
        parts += [f"({v}, None)" for v in pending]
        self.expect("INTO")
        into = self.ref().py
        pointer = "None"
        if self.accept("WITH") or self.word() == "POINTER":
            self.expect("POINTER")
            pointer = self.ref().py
        on_err, not_err = self.size_phrases(stop, "END-STRING", first="OVERFLOW", second=None)
        call = f"S.string([{', '.join(parts)}], {into}, {pointer})"
        return self.guarded(line, call, on_err, not_err)

    def s_UNSTRING(self, line, stop):
        src = self.ref().py
        delims = []
        if self.accept("DELIMITED"):
            self.accept("BY")
            while True:
                is_all = self.accept("ALL")
                delims.append(f"({self.value()}, {is_all})")
                if not self.accept("OR"):
                    break
        self.expect("INTO")
        tgts = []
        while self.is_data():
            r = self.ref().py
            din = cin = "None"
            if self.accept("DELIMITER"):
                self.accept("IN")
                din = self.ref().py
            if self.accept("COUNT"):
                self.accept("IN")
                cin = self.ref().py
            tgts.append(f"({r}, {din}, {cin})")
        pointer = tally = "None"
        if self.accept("WITH") or self.word() == "POINTER":
            self.expect("POINTER")
            pointer = self.ref().py
        if self.accept("TALLYING"):
            self.accept("IN")
            tally = self.ref().py
        on_err, not_err = self.size_phrases(stop, "END-UNSTRING", first="OVERFLOW", second=None)
        call = f"S.unstring({src}, [{', '.join(delims)}], [{', '.join(tgts)}], {pointer}, {tally})"
        return self.guarded(line, call, on_err, not_err)

    def _before_after(self):
        before = after = "None"
        while self.word() in ("BEFORE", "AFTER"):
            which = self.take().value
            self.accept("INITIAL")
            v = self.value()
            if which == "BEFORE":
                before = v
            else:
                after = v
        return before, after

    def s_INSPECT(self, line, stop):
        target = self.ref().py
        calls = []
        if self.accept("TALLYING"):
            while self.is_data():
                counter = self.ref().py
                self.expect("FOR")
                while True:
                    if self.accept("CHARACTERS"):
                        b, a = self._before_after()
                        calls.append(f'S.inspect_tally({target}, {counter}, "characters", None, {b}, {a})')
                    elif self.word() in ("ALL", "LEADING"):
                        mode = self.take().value.lower()
                        pat = self.value()
                        b, a = self._before_after()
                        calls.append(f'S.inspect_tally({target}, {counter}, "{mode}", {pat}, {b}, {a})')
                    else:
                        break
        if self.accept("REPLACING"):
            while True:
                if self.accept("CHARACTERS"):
                    self.expect("BY")
                    new = self.value()
                    b, a = self._before_after()
                    calls.append(f'S.inspect_replace({target}, "characters", None, {new}, {b}, {a})')
                elif self.word() in ("ALL", "LEADING", "FIRST"):
                    mode = self.take().value.lower()
                    while True:
                        pat = self.value()
                        self.expect("BY")
                        new = self.value()
                        b, a = self._before_after()
                        calls.append(f'S.inspect_replace({target}, "{mode}", {pat}, {new}, {b}, {a})')
                        if self.peek().kind != "str" and not (self.word() in FIGURATIVE):
                            break
                else:
                    break
        if self.accept("CONVERTING"):
            src = self.value()
            self.expect("TO")
            dst = self.value()
            b, a = self._before_after()
            calls.append(f"S.inspect_convert({target}, {src}, {dst}, {b}, {a})")
        if not calls:
            raise Unsupported("INSPECT form not supported yet")
        return self.code(line, "; ".join(calls))

    # SEARCH ------------------------------------------------------------------
    def s_SEARCH(self, line, stop):
        binary = self.accept("ALL")
        table = self.ref()
        if not table.item.indexes:
            raise Unsupported(f"SEARCH needs {table.item.name} to have INDEXED BY")
        index = table.item.indexes[0]
        varying = None
        if self.accept("VARYING"):
            name = self.take().value
            if name != index:  # another index or a counter steps along with the table's index
                if name in self.names.indexes:
                    varying = (name, f'S.idx_value("{name}")')
                elif name in self.names.by_name:
                    varying = (self.names.key[id(self.names.resolve(name, []))], None)
                    varying = (varying[0], f'S.n("{varying[0]}")')
                else:
                    raise Unsupported(f"unknown item {name} in SEARCH VARYING")
        at_end = None
        if self.word() in ("AT", "END") and self.word() != "END-SEARCH":
            self.accept("AT")
            self.expect("END")
            at_end = self.block(stop | {"WHEN", "END-SEARCH"})
        whens = []
        while self.accept("WHEN"):
            cond = self.condition()
            whens.append((cond, self.block(stop | {"WHEN", "END-SEARCH"})))
        self.accept("END-SEARCH")
        return Node("search", line, {"index": index, "count": table.item.occurs, "at_end": at_end or [], "whens": whens, "binary": binary,
                                     "varying": varying})


# ---------------------------------------------------------------- program structure

def _walk_up(item):
    """An item and the groups that hold it, and everything under it (where an OCCURS DEPENDING ON may sit)."""
    seen, out = set(), []
    stack = [item]
    while stack:
        it = stack.pop()
        if id(it) in seen:
            continue
        seen.add(id(it))
        out.append(it)
        stack += list(getattr(it, "children", []) or [])
    p = getattr(item, "parent", None)
    while p is not None:
        out.append(p)
        p = getattr(p, "parent", None)
    return out


def split_paragraphs(toks: list[Tok]) -> tuple[list[str], dict[str, list[Tok]], dict[str, tuple[str, str]], dict[str, int], dict[str, str | None]]:
    """Paragraph headers are one-word sentences; NAME SECTION starts a section. DECLARATIVES are skipped."""
    order, paras, lines = ["(start)"], {"(start)": []}, {"(start)": 0}
    sections: dict[str, list[str]] = {}
    owner: dict[str, str | None] = {"(start)": None}
    decls: list[tuple[str, list[str]]] = []  # (declarative section, the files or open modes its USE names)
    current, section = "(start)", None
    sentence: list[Tok] = []
    in_decl = False
    for tok in toks:
        sentence.append(tok)
        if tok.kind != "end":
            continue
        words = [t for t in sentence if t.kind != "end"]
        sentence = []
        if not words:
            continue
        vals = [w.value for w in words]
        if vals == ["DECLARATIVES"]:
            in_decl = True
            continue
        if vals[:2] == ["END", "DECLARATIVES"]:
            in_decl = False
            continue
        if in_decl and vals[0] == "USE":
            if section and "DEBUGGING" in vals:
                # USE FOR DEBUGGING: GnuCOBOL runs these only when COB_SET_DEBUG is set at run time (measured), which
                # Séance never sets; they are declaratives all the same, so a run does not start in them
                decls.append((section, ["(FOR DEBUGGING)"]))
            elif section:
                skip = {"AFTER", "STANDARD", "EXCEPTION", "ERROR", "PROCEDURE", "ON", "GLOBAL"}
                decls.append((section, [v for v in vals[1:] if v not in skip]))
            continue
        named = words[0].kind == "word" or (words[0].kind == "num" and vals[0].isdigit())  # a procedure name may be digits only
        if (len(words) == 2 or (len(words) == 3 and words[2].kind == "num")) and vals[1] == "SECTION" and named:
            # NAME SECTION, or NAME SECTION 50 with a segment number (a priority that only matters to overlays)
            section = vals[0]
            current = vals[0]
            order.append(current)
            paras[current], lines[current] = [], words[0].line
            sections[section] = [current]
            owner[current] = None
            continue
        if len(words) == 1 and named and vals[0] not in VERBS and vals[0] not in ENDERS:
            current = vals[0]
            if current in paras:
                current = f"{current}@{section}"
            order.append(current)
            owner[current] = section
            paras[current], lines[current] = [], words[0].line
            if section:
                sections[section].append(current)
            continue
        paras[current].extend(words + [Tok("end", ".", words[-1].line)])
    if not paras["(start)"]:
        order.remove("(start)")
        del paras["(start)"]
    secs = {s: (members[0], members[-1]) for s, members in sections.items()}
    return order, paras, secs, lines, owner, decls  # owner: the section each paragraph is in


@dataclass
class Translation:
    program: str
    code: str
    statements: int
    unsupported: list[dict]
    record_paragraph: str = ""


class Emitter:
    def __init__(self, tag: str = "L"):
        self.unsupported: list[dict] = []
        self.count = 0
        self.tag = tag  # "L" for the main program; "HELLO L" for a called one, so its lines never pose as main-program lines

    @staticmethod
    def fname(p: str) -> str:
        return "p_" + re.sub(r"[^a-z0-9_]", "_", p.lower().replace("-", "_"))

    def lines(self, nodes: list[Node], ind: int) -> list[str]:
        pad = "    " * ind
        out: list[str] = []
        for n in nodes:
            k, d = n.kind, n.data
            tag = f"  # {self.tag}{n.line}"
            self.count += 1
            if k == "code":
                out.append(f"{pad}{d['py']}{tag}")
            elif k == "guarded":
                out.append(f"{pad}if not {d['call']}:{tag}")
                out += self.lines(d["on_err"], ind + 1) or [pad + "    pass"]
                if d["not_err"]:
                    out.append(f"{pad}else:")
                    out += self.lines(d["not_err"], ind + 1)
            elif k == "if":
                out.append(f"{pad}if {d['cond']}:{tag}")
                out += self.lines(d["then"], ind + 1) or [pad + "    pass"]
                if d["else"]:
                    out.append(f"{pad}else:")
                    out += self.lines(d["else"], ind + 1)
            elif k == "evaluate":
                merged = []
                for cond, body in d["branches"]:  # consecutive WHENs with no body share the next body
                    if merged and not merged[-1][1] and merged[-1][0] is not None and cond is not None:
                        merged[-1] = (f"{merged[-1][0]} or {cond}", body)
                    else:
                        merged.append((cond, body))
                first = True
                for cond, body in merged:
                    if cond is None:
                        out.append(f"{pad}{'if True' if first else 'else'}:{tag if first else ''}")
                    else:
                        out.append(f"{pad}{'if' if first else 'elif'} {cond}:{tag if first else ''}")
                    out += self.lines(body, ind + 1) or [pad + "    pass"]
                    first = False
                if first:
                    out.append(f"{pad}pass{tag}")
            elif k == "loop":
                out += self.loop(n, ind)
            elif k == "search":
                ix = d["index"]
                if d["binary"]:
                    out.append(f'{pad}S.set_index("{ix}", 1)  # SEARCH ALL: the table is in key order, so the first match is the match{tag}')
                out.append(f"{pad}for _ in S.loop():{tag}")
                out.append(f'{pad}    if S.idx_value("{ix}") > {d["count"]}:')
                out += self.lines(d["at_end"], ind + 2)
                out.append(f"{pad}        break")
                for j, (cond, body) in enumerate(d["whens"]):
                    out.append(f"{pad}    {'if' if j == 0 else 'elif'} {cond}:")
                    out += self.lines(body, ind + 2)
                    out.append(f"{pad}        break")
                out.append(f'{pad}    S.set_index("{ix}", S.idx_value("{ix}") + 1)')
                if d.get("varying"):
                    name, current = d["varying"]
                    out.append(f'{pad}    S.set_index("{name}", {current} + 1)')
            elif k == "goto":
                if "depending" in d:
                    targets = ", ".join(f'"{t}"' for t in d["targets"])
                    out.append(f"{pad}_k = int({d['depending']}){tag}")
                    out.append(f"{pad}if 1 <= _k <= {len(d['targets'])}:")
                    out.append(f"{pad}    return [{targets}][_k - 1]")
                elif "alter" in d:
                    first = d["targets"][0]
                    out.append(f'{pad}return S.altered("{d["alter"]}", {first!r}){tag}  # GO TO, re-pointed by ALTER')
                else:
                    out.append(f'{pad}return "{d["targets"][0]}"{tag}  # GO TO')
            elif k == "stop":
                out.append(f"{pad}raise StopRun(){tag}")
            elif k == "goback":
                out.append(f"{pad}raise GoBack(){tag}")
            elif k == "next_sentence":
                out.append(f"{pad}raise NextSentence(){tag}  # NEXT SENTENCE")
            elif k == "sentence":
                out.append(f"{pad}try:  # a sentence with NEXT SENTENCE in it")
                out += self.lines(d["body"], ind + 1) or [pad + "    pass"]
                out.append(f"{pad}except NextSentence:")
                out.append(f"{pad}    pass")
            elif k == "return":
                out.append(f"{pad}return None{tag}  # EXIT PARAGRAPH")
            elif k == "exit_section":
                out.append(f'{pad}return "__exit_section__"{tag}')
            elif k == "break":
                out.append(f"{pad}break{tag}  # EXIT PERFORM")
            elif k == "continue":
                out.append(f"{pad}continue{tag}  # EXIT PERFORM CYCLE")
            elif k == "unsupported":
                self.unsupported.append({"line": n.line, "text": d["text"], "why": d["why"]})
                note = d["text"][:70].replace("\\", "/").replace('"', "'")
                out.append(f'{pad}S.unsupported("line {n.line}: {note}"){tag} {d["why"]}')
        return out

    def loop(self, n: Node, ind: int) -> list[str]:
        pad = "    " * ind
        mode, body = n.data["mode"], n.data["body"]
        tag = f"  # L{n.line}"
        if mode[0] == "once":
            return self.lines(body, ind)
        out: list[str] = []
        if mode[0] == "times":
            out.append(f"{pad}for _ in range(max(0, int({mode[1]}))):{tag}")
            out += self.lines(body, ind + 1) or [pad + "    pass"]
        elif mode[0] == "forever":
            out.append(f"{pad}for _ in S.loop():{tag}")
            out += self.lines(body, ind + 1) or [pad + "    pass"]
        elif mode[0] == "until":
            cond, after = mode[1], mode[2]
            out.append(f"{pad}for _ in S.loop():{tag}")
            if not after:
                out += [f"{pad}    if {cond}:", f"{pad}        break"]
            out += self.lines(body, ind + 1) or [pad + "    pass"]
            if after:
                out += [f"{pad}    if {cond}:", f"{pad}        break"]
        elif mode[0] == "varying":
            levels, after = mode[1], mode[2]

            def setv(var, val):
                kind, v = var
                return f'S.set_index("{v}", int({val}))' if kind == "idx" else f"S.compute([({v.target}, lambda: {val}, False)])"

            def getv(var):
                kind, v = var
                return f'D(S.idx_value("{v}"))' if kind == "idx" else v.num

            def nest(level: int, depth: int) -> list[str]:
                p = "    " * depth
                var, start, step, cond = levels[level]
                lines = [f"{p}{setv(var, start)}", f"{p}for _ in S.loop():"]
                if not after:
                    lines += [f"{p}    if {cond}:", f"{p}        break"]
                if level + 1 < len(levels):
                    lines += nest(level + 1, depth + 1)
                else:
                    lines += self.lines(body, depth + 1) or [p + "    pass"]
                if after:
                    lines += [f"{p}    if {cond}:", f"{p}        break"]
                lines.append(f"{p}    {setv(var, getv(var) + ' + ' + step)}")
                return lines

            out.append(f"{pad}pass{tag}  # PERFORM VARYING")
            out += nest(0, ind)
        return out


def _lit(v) -> str:
    if isinstance(v, Decimal):
        return f'D("{v}")'
    if isinstance(v, str) and v in ("SPACE", "ZERO", "HIGH", "LOW", "QUOTE"):
        return v
    return repr(v)


def _data_literals(names: Names, records: dict[str, int], model: ProgramModel) -> str:
    items, values, conds = [], [], []
    for key, it in names.items.items():
        spec = it.spec()
        spec[11] = [names.key[id(c)] for c in it.children if not c.redefines]  # INITIALIZE leaves REDEFINES out
        items.append(f'    "{key}": {spec!r},')
        in_ws = it.record in {r.name for r in model.ws_records}
        if it.value is not None and in_ws:
            values.append(f'    ("{key}", {_lit(it.value)}, {it.value_all}),')
    for cname, (key, choices, false) in names.conds.items():
        tail = f", {_lit(false)}" if false is not None else ""
        conds.append(f'    "{cname}": ("{key}", [{", ".join(f"({_lit(lo)}, {_lit(hi) if hi is not None else None})" for lo, hi in choices)}]{tail}),')
    files = []
    for f in model.files:
        if not f.records:
            continue
        status = names.key[id(names.resolve(f.status, []))] if f.status and f.status in names.by_name else None

        def key_of(n):
            return names.key[id(names.resolve(n, []))] if n and n in names.by_name else None
        extra = {"access": f.access}
        if f.optional:
            extra["optional"] = True
        if f.variable:
            extra["variable"] = True
        if f.organization == "indexed":
            extra["key"] = key_of(f.record_key)
            extra["alt"] = [[key_of(k), d] for k, d in f.alt_keys]
        if f.organization == "relative" and f.relative_key:
            extra["relkey"] = key_of(f.relative_key)
        if f.linage:
            lin = {k: (key_of(v) if isinstance(v, str) else v) for k, v in f.linage.items()}
            lin["counter"] = names.key[id(names.linage_items[f.name])]
            extra["linage"] = lin
        if f.depending and f.depending in names.by_name:
            extra["depending"] = key_of(f.depending)  # RECORD VARYING ... DEPENDING ON
        if f.same_record:  # SAME RECORD AREA: the buffer is shared, so WRITE finds the file by its own records
            extra["records"] = [names.key[id(r)] for r in f.records]
        buffer = names.file_buffer.get(f.name, f.records[0].name)
        files.append(f'    ["{f.name}", "{f.assign}", "{f.organization}", "{buffer}", {f.size}, {status!r}, {extra!r}],')
    return ("ITEMS = {\n" + "\n".join(items) + "\n}\n\n"
            + f"RECORDS = {records!r}\n\n"
            + "VALUES = [\n" + "\n".join(values) + "\n]\n\n"
            + "CONDITIONS = {\n" + "\n".join(conds) + "\n}\n\n"
            + "FILES = [\n" + "\n".join(files) + "\n]\n\n"
            + f"INDEXES = {sorted(names.indexes)!r}\n")


def _has(nodes, kind) -> bool:
    for n in nodes:
        if n.kind == kind:
            return True
        for v in n.data.values() if isinstance(n.data, dict) else []:
            if isinstance(v, list):
                if any(isinstance(x, Node) for x in v) and _has([x for x in v if isinstance(x, Node)], kind):
                    return True
                for x in v:
                    if isinstance(x, tuple) and any(isinstance(y, list) and _has([z for z in y if isinstance(z, Node)], kind) for y in x):
                        return True
    return False


def _unit(model: ProgramModel, tag: str) -> dict:
    """Translate one program (the main one or a called one) into its data literals and paragraph functions."""
    names, records = build_names(model)
    src_lines = normalize(read_source(model.source or model.path), model.fixed, model.copy_dirs or None)
    start = next((i for i, l in enumerate(src_lines) if not l.comment and re.match(r"^\s*PROCEDURE\s+DIVISION", l.text, re.I)), None)
    if start is None:
        raise Unsupported("no PROCEDURE DIVISION")
    toks = tokenize_lines(src_lines[start:])
    first_end = next(i for i, t in enumerate(toks) if t.kind == "end")
    toks = toks[first_end + 1:]  # skip the PROCEDURE DIVISION header, even when USING runs onto more lines
    for i in range(len(toks) - 1):
        if toks[i].value == "END" and toks[i + 1].value == "PROGRAM":
            toks = toks[:i]
            break
    order, ptoks, sections, plines, owner, decls = split_paragraphs(toks)
    names.debug_sections = {s for s, targets in decls if targets == ["(FOR DEBUGGING)"]}
    known = set(order) | set(sections)
    altered = {toks[i + 1].value for i in range(len(toks) - 1) if toks[i].value == "ALTER" and toks[i].kind == "word"}
    parsed: dict[str, list[Node]] = {}
    for p in order:
        parser = Parser(ptoks[p], names, known, owner.get(p) if p not in sections else p, owner, p, altered)
        nodes: list[Node] = []
        while parser.i < len(parser.t):
            sentence = parser.block(set())
            if _has(sentence, "next_sentence"):
                sentence = [Node("sentence", sentence[0].line if sentence else 0, {"body": sentence})]
            nodes += sentence
            if parser.peek().kind == "end":
                parser.i += 1
            elif parser.i < len(parser.t):
                tok = parser.take()
                nodes.append(Node("unsupported", tok.line, {"text": tok.value, "why": f"unexpected {tok.value}"}))
        parsed[p] = nodes
    em = Emitter(tag)
    funcs = []
    for p in order:
        body = em.lines(parsed[p], 1)
        label = "statements before the first paragraph" if p == "(start)" else f"{'section' if p in sections else 'paragraph'} {p}"
        funcs.append(f"def {em.fname(p)}():  # {label} (line {plines.get(p, 0)})\n" + "\n".join(body or ["    pass"]) + "\n")
    para_list = ",\n".join(f'    ("{p}", {em.fname(p)})' for p in order)
    linkage = [names.key[id(r)] for r in model.linkage_records if r.name in model.using]
    linkage.sort(key=lambda k: model.using.index(names.items[k].name))
    return {"data": _data_literals(names, records, model), "funcs": funcs, "paras": para_list, "sections": sections,
            "gaps": em.unsupported, "count": em.count, "linkage": linkage, "decls": decls}


def _collating_line(model: ProgramModel) -> str:
    """S.collating for a program with a PROGRAM COLLATING SEQUENCE that is not the native order."""
    sp = getattr(model, "special", None)
    table = sp.collating() if sp is not None else None
    if table is None:
        return ""
    return (f"S.collating = bytes.fromhex(\"{table.hex()}\")  # PROGRAM COLLATING SEQUENCE IS {sp.program_collating}: "
            "alphanumeric comparisons of data and SORT keys go by these weights\n")


def _indent(text: str, n: int = 1) -> str:
    pad = "    " * n
    return "\n".join(pad + line if line.strip() else line for line in text.split("\n"))


def translate(program: str, root: Path = ROOT) -> Translation:
    try:
        model = load_model(program, root)
    except ModelError as exc:
        raise Unsupported(str(exc)) from exc
    main = _unit(model, "L")
    gaps = list(main["gaps"])
    count = main["count"]
    subs_code = []
    called = [m for m in model._every()[1:]]
    for sub in called:
        u = _unit(sub, f"{sub.program_id} L")
        for g in u["gaps"]:
            gaps.append({**g, "text": f"{sub.program_id}: {g['text']}"})
        count += u["count"]
        fn = "_program_" + re.sub(r"[^a-z0-9_]", "_", sub.program_id.lower())
        body = (u["data"]
                + f"\nS = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage={u['linkage']!r}, initial={sub.initial})\n"
                + _collating_line(sub) + "\n\n"
                + "\n\n".join(u["funcs"])
                + "\n\nPARAGRAPHS = [\n" + u["paras"] + ",\n]\n"
                + f"SECTIONS = {u['sections']!r}\n"
                + (f"S.declaratives = {u['decls']!r}  # USE AFTER ERROR PROCEDURE: section, files or open modes\n" if u["decls"] else "")
                + "return S, PARAGRAPHS, SECTIONS\n")
        subs_code.append(f"def {fn}():\n"
                         f'    """Called program {sub.program_id} (legacy/{program}/{sub.path.name}). Lines end with # {sub.program_id} Lnn."""\n'
                         + _indent(body) + "\n")
    registry = "{" + ", ".join(f'"{m.program_id}": _program_{re.sub(r"[^a-z0-9_]", "_", m.program_id.lower())}()' for m in called) + "}"
    io_note = model.describe_io()
    header = (
        f'"""Python translation of legacy/{program}/{program}.cbl (PROGRAM-ID {model.program_id}).\n\n'
        f"Written by the Séance translator on {_dt.date.today().isoformat()}. The program {io_note}.\n"
        "Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).\n"
        "Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.\n"
        + (f"{len(gaps)} statement(s) could not be translated; they raise NotImplementedError naming the line:\n"
           + "".join(f"  - line {g['line']}: {g['text'][:60]} ({g['why']})\n" for g in gaps)
           if gaps else "Every statement was translated.\n")
        + 'This file is yours now: edit it, then run the check.\n"""\n'
    )
    all_files = [[f.name, f.assign] for f in model.all_files]
    code = (
        header
        + "\nfrom decimal import Decimal as D\n\n"
        + "from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, Lit, NextSentence, Program, StopRun, run_cli\n\n"
        + main["data"]
        + f"\nS = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage={main['linkage']!r})\n"
        + ("S.comma = True  # DECIMAL-POINT IS COMMA: numbers are shown and read as 1.234,50\n" if model.decimal_comma else "")
        + (f"S.currency = {model.currency!r}  # CURRENCY SIGN: edited fields show it where the picture has $\n"
           if getattr(model, "currency", "$") != "$" else "")
        + _collating_line(model)
        + "\n\n"
        + "\n\n".join(main["funcs"])
        + "\n\nPARAGRAPHS = [\n" + main["paras"] + ",\n]\n"
        + f"SECTIONS = {main['sections']!r}\n"
        + (f"S.declaratives = {main['decls']!r}  # USE AFTER ERROR PROCEDURE: section, files or open modes\n" if main["decls"] else "")
        + "\n\n"
        + ("\n\n".join(subs_code) + f"\n\nS.link({registry})\n\n\n" if subs_code else "")
        + f"RUN_FILES = {all_files!r}  # every file the run touches, in this program and the programs it calls\n\n\n"
        + "def main(io=None):\n"
        + '    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""\n'
        + "    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)\n\n\n"
        + 'if __name__ == "__main__":\n'
        + "    raise SystemExit(run_cli(main, RUN_FILES))\n"
    )
    compile(code, f"migrated/{program}.py", "exec")  # never hand over a draft that does not parse
    return Translation(program, code, count, gaps, "")


def write_draft(program: str, root: Path = ROOT, overwrite: bool = False) -> tuple[Path, Translation]:
    tr = translate(program, root)
    target = root / "migrated" / f"{program}.py"
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target.relative_to(root).as_posix()} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    (target.parent / "__init__.py").touch()
    target.write_text(tr.code, encoding="utf-8")
    return target, tr
