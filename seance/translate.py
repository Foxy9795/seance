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

from .cobol_src import normalize
from .layout import Item, walk
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
      | (?P<num>\d+\.\d+|\.\d+|\d+(?![A-Za-z0-9_-]))
      | (?P<op>\*\*|>=|<=|<>|[()+\-*/=<>:&])
      | (?P<word>[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]|[A-Za-z0-9])
    """,
    re.X,
)


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
    conds: dict[str, tuple[str, list]] = field(default_factory=dict)
    indexes: dict[str, str] = field(default_factory=dict)  # index name -> table item key
    files: dict[str, object] = field(default_factory=dict)  # FD name -> FileDef

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


def build_names(model: ProgramModel) -> tuple[Names, dict[str, int]]:
    names = Names()
    records: dict[str, int] = {}
    for f in model.files:
        if not f.records:
            continue
        buffer = f.records[0].name
        records[buffer] = f.size
        names.files[f.name] = f
        for r in f.records:
            for it in walk(r):
                names.add(it, buffer)
    for r in model.ws_records:
        buffer = r.name
        if r.redefines and r.redefines in records:  # 01 B REDEFINES A: B is another view of A's storage
            buffer = r.redefines
            while buffer in names.by_name and names.by_name[buffer][0].record != buffer:
                buffer = names.by_name[buffer][0].record
        records[buffer] = max(records.get(buffer, 0), r.size, 1)
        for it in walk(r):
            names.add(it, buffer)
    special = Item("RETURN-CODE", 1, kind="num", usage="native", digits=9, signed=True, size=4)
    records["_SPECIAL"] = 6
    names.add(special, "_SPECIAL")
    tally = Item("TALLY", 1, kind="num", usage="native", digits=5, signed=False, size=2, offset=4)
    names.add(tally, "_SPECIAL")
    names.finish()
    for it in names.items.values():
        k = names.key[id(it)]
        for cname, choices in it.conds:
            names.conds[cname] = (k, choices)
        for ix in it.indexes:
            names.indexes[ix] = k
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
    def __init__(self, toks: list[Tok], names: Names, paragraphs: set[str]):
        self.t, self.i, self.names, self.paras = toks, 0, names, paragraphs
        self._last = None

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
        return tok.kind == "word" and tok.value in self.names.by_name and tok.value not in self.names.conds

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
        item = self.names.resolve(tok.value, quals)
        key = self.names.key[id(item)]
        py = f'S.r("{key}"'
        simple = True
        if self.is_op("(") and item.dims():
            self.i += 1
            subs = []
            while not self.is_op(")"):
                if self.peek().kind == "end":
                    raise Unsupported("unclosed subscript")
                subs.append(self.subscript())
            self.i += 1
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
        return self.ref().py

    def function(self) -> str:
        self.expect("FUNCTION")
        name = self.take().value
        from .rt import F

        attr = name.replace("-", "_")
        if not hasattr(F, attr):
            raise Unsupported(f"FUNCTION {name} is not supported yet")
        args = []
        if self.is_op("(") and not self._refmod_ahead():  # FUNCTION CURRENT-DATE (1:8) is a substring, not arguments
            self.i += 1
            while not self.is_op(")"):
                if self.peek().kind == "end":
                    raise Unsupported("unclosed function arguments")
                if self.word() in ("LEADING", "TRAILING") and attr == "TRIM":
                    args.append(repr(self.take().value))
                    continue
                if attr in TEXT_FUNCTIONS:  # these take text: FUNCTION LOWER-CASE(NAME(2:19)) must not read NAME as a number
                    args.append(self._text_arg())
                    continue
                save = self.i
                try:
                    args.append(self.expr())
                    if not (self.is_op(")") or self.peek().kind in ("word", "num", "str")):
                        raise Unsupported("")
                except Unsupported:
                    self.i = save
                    args.append(self._text_arg())
            self.i += 1
        call = f"F.{attr}({', '.join(args)})"
        if self.is_op("(") and self._refmod_ahead():
            self.i += 1
            start = self.expr()
            self.i += 1  # ':'
            length = None if self.is_op(")") else self.expr()
            self.i += 1
            call = f"{call}[int({start}) - 1:{'int(' + start + ') - 1 + int(' + length + ')' if length else ''}]"
        return call

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
        if tok.kind == "num":
            self.i += 1
            return f'D("{tok.value}")'
        if tok.kind == "word" and tok.value in ("ZERO", "ZEROS", "ZEROES"):
            self.i += 1
            return 'D("0")'
        if tok.kind == "word" and tok.value == "FUNCTION":
            return f"D({self.function()})"
        if tok.kind == "word" and tok.value in self.names.indexes:
            self.i += 1
            return f'D(S.idx_value("{tok.value}"))'
        if tok.kind == "word" and tok.value in ("RETURN-CODE", "TALLY"):
            self.i += 1
            return f'S.n("{tok.value}")'
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

    def cond_primary(self) -> str:
        if self._last and (self.relop_ahead(0) or (self.word() == "NOT" and self.relop_ahead(1))):
            subject = self._last[0]
            op = self.relop()
            obj = self.comparand()
            self._last = (subject, op)
            return f'S.cmp({subject}, "{op}", {obj})'
        tok = self.peek()
        if tok.kind == "word" and tok.value in self.names.conds:
            self.i += 1
            subs = ""
            if self.is_op("("):
                self.i += 1
                parts = []
                while not self.is_op(")"):
                    parts.append(self.subscript())
                self.i += 1
                subs = ", " + ", ".join(parts)
            return f'S.cond("{tok.value}"{subs})'
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

    def targets(self, allow_rounded=True) -> list[tuple[RefX, bool]]:
        out = []
        while self.is_data():
            r = self.ref()
            rounded = allow_rounded and self.accept("ROUNDED")
            out.append((r, rounded))
        if not out:
            raise Unsupported(f"expected a receiving field near {self.peek().value!r}")
        return out

    def specs(self, items) -> str:
        return "[" + ", ".join(f"({r.target}, lambda: {e}, {rounded})" for r, e, rounded in items) + "]"

    # MOVE / INITIALIZE / SET ------------------------------------------------
    def s_MOVE(self, line, stop):
        if self.word() in ("CORRESPONDING", "CORR"):
            raise Unsupported("MOVE CORRESPONDING is not supported yet")
        src = self.value()
        self.expect("TO")
        names = [r.target for r, _ in self.targets(allow_rounded=False)]
        return self.code(line, f"S.move({src}, {', '.join(names)})")

    def s_INITIALIZE(self, line, stop):
        names = [r.target for r, _ in self.targets(allow_rounded=False)]
        if self.word() in ("REPLACING", "WITH", "ALL", "TO"):
            raise Unsupported("INITIALIZE ... REPLACING is not supported yet")
        return self.code(line, f"S.initialize({', '.join(names)})")

    def s_SET(self, line, stop):
        if self.word() in self.names.conds:
            name = self.take().value
            self.expect("TO")
            if self.accept("TRUE"):
                return self.code(line, f'S.set_true("{name}")')
            raise Unsupported("SET condition TO FALSE is not supported yet")
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
        if self.word() in ("CORRESPONDING", "CORR"):
            raise Unsupported("ADD CORRESPONDING is not supported yet")
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
        if self.word() in ("CORRESPONDING", "CORR"):
            raise Unsupported("SUBTRACT CORRESPONDING is not supported yet")
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
        if self.is_data() and self.word(1) != "GIVING" and not (self.is_op("(", 1)):
            dests = self.targets()
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
            if self.is_data() and self.word(1) not in ("GIVING",) and not self.is_op("(", 1):
                dests = self.targets()
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
        if self.word() == "NEXT" and self.word(1) == "SENTENCE":
            raise Unsupported("NEXT SENTENCE is not supported yet")
        then = self.block(stop | {"ELSE", "END-IF"})
        other: list[Node] = []
        if self.accept("ELSE"):
            other = self.block(stop | {"END-IF"})
        self.accept("END-IF")
        return Node("if", line, {"cond": cond, "then": then, "else": other})

    def s_EVALUATE(self, line, stop):
        subjects = [None if self.accept("TRUE") else ("FALSE" if self.accept("FALSE") else self.comparand())]
        while self.accept("ALSO"):
            subjects.append(None if self.accept("TRUE") else ("FALSE" if self.accept("FALSE") else self.comparand()))
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
        negate = self.accept("NOT")
        lo = self.comparand()
        if self.accept("THRU", "THROUGH"):
            hi = self.comparand()
            test = f'S.cmp({subject}, ">=", {lo}) and S.cmp({subject}, "<=", {hi})'
        else:
            test = f'S.cmp({subject}, "==", {lo})'
        return f"not ({test})" if negate else test

    def s_PERFORM(self, line, stop):
        target = self.word()
        if target in self.paras:
            self.i += 1
            last = None
            if self.accept("THRU", "THROUGH"):
                last = self.take().value
            mode = self.loop_mode()
            call = f'S.perform("{target}"' + (f', "{last}"' if last else "") + ")"
            return Node("loop", line, {"mode": mode, "body": [self.code(line, call)]})
        mode = self.loop_mode()
        body = self.block(stop | {"END-PERFORM"})
        self.expect("END-PERFORM")
        return Node("loop", line, {"mode": mode, "body": body, "inline": True})

    def loop_mode(self):
        if self.accept("WITH"):
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
        while self.word() in self.paras:
            targets.append(self.take().value)
        if not targets:
            raise Unsupported("GO TO without a paragraph name (ALTER) is not supported")
        if self.accept("DEPENDING"):
            self.accept("ON")
            sel = self.operand_num()
            return Node("goto", line, {"targets": targets, "depending": sel})
        return Node("goto", line, {"targets": targets})

    def s_STOP(self, line, stop):
        if self.accept("RUN"):
            return Node("stop", line)
        raise Unsupported("STOP with a literal is not supported")

    def s_GOBACK(self, line, stop):
        return Node("stop", line)

    def s_EXIT(self, line, stop):
        if self.accept("PARAGRAPH"):
            return Node("return", line)
        if self.accept("SECTION"):
            return Node("exit_section", line)
        if self.accept("PROGRAM"):
            return Node("stop", line)
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
                calls.append(f'S.close("{w}")')
        return self.code(line, "; ".join(calls) or "pass")

    def s_READ(self, line, stop):
        file = self.take().value
        if file not in self.names.files:
            raise Unsupported(f"READ of unknown file {file}")
        self.accept("NEXT")
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
        if self.word() in ("INVALID", "KEY"):
            raise Unsupported("READ ... INVALID KEY is for indexed files, which are not supported")
        self.accept("END-READ")
        call = f'S.read("{file}"' + (f", {into}" if into else "") + ")"
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
        if self.word() in ("AT", "END-OF-PAGE", "EOP") or (self.word() == "NOT" and self.word(1) in ("AT", "END-OF-PAGE", "EOP")):
            raise Unsupported("WRITE ... AT END-OF-PAGE (LINAGE) is not supported yet")
        self.accept("END-WRITE")
        return self.code(line, f'S.write("{rec.key}", {src or "None"}, {adv})')

    def s_DISPLAY(self, line, stop):
        parts = []
        upon, no_adv = "console", False
        while not self.at_boundary(stop):
            if self.accept("UPON"):
                dev = self.take().value
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
                parts.append(repr(text))
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
            elif w in ("CONSOLE", "SYSIN", "STDIN"):
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
            if self.word() == "NEXT" and self.word(1) == "SENTENCE":
                raise Unsupported("NEXT SENTENCE is not supported yet")
            whens.append((cond, self.block(stop | {"WHEN", "END-SEARCH"})))
        self.accept("END-SEARCH")
        return Node("search", line, {"index": index, "count": table.item.occurs, "at_end": at_end or [], "whens": whens, "binary": binary,
                                     "varying": varying})


# ---------------------------------------------------------------- program structure

def split_paragraphs(toks: list[Tok]) -> tuple[list[str], dict[str, list[Tok]], dict[str, tuple[str, str]], dict[str, int]]:
    """Paragraph headers are one-word sentences; NAME SECTION starts a section. DECLARATIVES are skipped."""
    order, paras, lines = ["(start)"], {"(start)": []}, {"(start)": 0}
    sections: dict[str, list[str]] = {}
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
        if in_decl:
            continue
        if len(words) == 2 and vals[1] == "SECTION" and words[0].kind == "word":
            section = vals[0]
            current = vals[0]
            order.append(current)
            paras[current], lines[current] = [], words[0].line
            sections[section] = [current]
            continue
        if len(words) == 1 and words[0].kind == "word" and vals[0] not in VERBS and vals[0] not in ENDERS:
            current = vals[0]
            if current in paras:
                current = f"{current}@{section}"
            order.append(current)
            paras[current], lines[current] = [], words[0].line
            if section:
                sections[section].append(current)
            continue
        paras[current].extend(words + [Tok("end", ".", words[-1].line)])
    if not paras["(start)"]:
        order.remove("(start)")
        del paras["(start)"]
    secs = {s: (members[0], members[-1]) for s, members in sections.items()}
    return order, paras, secs, lines


@dataclass
class Translation:
    program: str
    code: str
    statements: int
    unsupported: list[dict]
    record_paragraph: str = ""


class Emitter:
    def __init__(self):
        self.unsupported: list[dict] = []
        self.count = 0

    @staticmethod
    def fname(p: str) -> str:
        return "p_" + re.sub(r"[^a-z0-9_]", "_", p.lower().replace("-", "_"))

    def lines(self, nodes: list[Node], ind: int) -> list[str]:
        pad = "    " * ind
        out: list[str] = []
        for n in nodes:
            k, d = n.kind, n.data
            tag = f"  # L{n.line}"
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
                else:
                    out.append(f'{pad}return "{d["targets"][0]}"{tag}  # GO TO')
            elif k == "stop":
                out.append(f"{pad}raise StopRun(){tag}")
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
        spec[11] = [names.key[id(c)] for c in it.children]
        items.append(f'    "{key}": {spec!r},')
        in_ws = it.record in {r.name for r in model.ws_records}
        if it.value is not None and in_ws:
            values.append(f'    ("{key}", {_lit(it.value)}, {it.value_all}),')
    for cname, (key, choices) in names.conds.items():
        conds.append(f'    "{cname}": ("{key}", [{", ".join(f"({_lit(lo)}, {_lit(hi) if hi is not None else None})" for lo, hi in choices)}]),')
    files = []
    for f in model.files:
        if not f.records:
            continue
        status = names.key[id(names.resolve(f.status, []))] if f.status and f.status in names.by_name else None
        files.append(f'    ["{f.name}", "{f.assign}", "{"line" if f.organization == "line" else "sequential"}", "{f.records[0].name}", {f.size}, {status!r}],')
    return ("ITEMS = {\n" + "\n".join(items) + "\n}\n\n"
            + f"RECORDS = {records!r}\n\n"
            + "VALUES = [\n" + "\n".join(values) + "\n]\n\n"
            + "CONDITIONS = {\n" + "\n".join(conds) + "\n}\n\n"
            + "FILES = [\n" + "\n".join(files) + "\n]\n\n"
            + f"INDEXES = {sorted(names.indexes)!r}\n")


def translate(program: str, root: Path = ROOT) -> Translation:
    try:
        model = load_model(program, root)
    except ModelError as exc:
        raise Unsupported(str(exc)) from exc
    names, records = build_names(model)
    src_lines = normalize(model.path.read_text(encoding="utf-8", errors="replace"), model.fixed)
    start = next((i for i, l in enumerate(src_lines) if not l.comment and re.match(r"^\s*PROCEDURE\s+DIVISION", l.text, re.I)), None)
    if start is None:
        raise Unsupported("no PROCEDURE DIVISION")
    proc_lines = src_lines[start + 1:]
    # PROCEDURE DIVISION header may continue onto the next line (USING ...); copybooks there are rare
    toks = tokenize_lines(proc_lines)
    order, ptoks, sections, plines = split_paragraphs(toks)
    known = set(order) | set(sections)
    parsed: dict[str, list[Node]] = {}
    for p in order:
        parser = Parser(ptoks[p], names, known)
        nodes: list[Node] = []
        while parser.i < len(parser.t):
            nodes += parser.block(set())
            if parser.peek().kind == "end":
                parser.i += 1
            elif parser.i < len(parser.t):
                tok = parser.take()
                nodes.append(Node("unsupported", tok.line, {"text": tok.value, "why": f"unexpected {tok.value}"}))
        parsed[p] = nodes

    em = Emitter()
    funcs = []
    for p in order:
        body = em.lines(parsed[p], 1)
        label = "statements before the first paragraph" if p == "(start)" else f"{'section' if p in sections else 'paragraph'} {p}"
        funcs.append(f"def {em.fname(p)}():  # {label} (line {plines.get(p, 0)})\n" + "\n".join(body or ["    pass"]) + "\n")
    gaps = em.unsupported
    for why in model.unsupported:
        if not any(why.split()[0].upper() in g["text"].upper() for g in gaps):
            pass
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
    para_list = ",\n".join(f'    ("{p}", {em.fname(p)})' for p in order)
    code = (
        header
        + "\nfrom decimal import Decimal as D\n\n"
        + "from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, Program, StopRun, run_cli\n\n"
        + _data_literals(names, records, model)
        + "\nS = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES)\n\n\n"
        + "\n\n".join(funcs)
        + "\n\nPARAGRAPHS = [\n" + para_list + ",\n]\n"
        + f"SECTIONS = {sections!r}\n\n\n"
        + "def main(io=None):\n"
        + '    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""\n'
        + "    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)\n\n\n"
        + 'if __name__ == "__main__":\n'
        + "    raise SystemExit(run_cli(main, FILES))\n"
    )
    compile(code, f"migrated/{program}.py", "exec")  # never hand over a draft that does not parse
    return Translation(program, code, em.count, gaps, "")


def write_draft(program: str, root: Path = ROOT, overwrite: bool = False) -> tuple[Path, Translation]:
    tr = translate(program, root)
    target = root / "migrated" / f"{program}.py"
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target.relative_to(root).as_posix()} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    (target.parent / "__init__.py").touch()
    target.write_text(tr.code, encoding="utf-8")
    return target, tr
