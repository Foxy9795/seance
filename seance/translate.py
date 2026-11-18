"""Translate a COBOL batch program into a first-draft Python migration.

Deterministic and rule-based: it parses the PROCEDURE DIVISION into statements, finds the per-record
work inside the read loop, and writes one Python line per COBOL statement on top of seance.runtime.
Anything it cannot convert becomes a call that raises NotImplementedError naming the COBOL line, so a
check fails loudly at that spot instead of passing quietly. The verifier, not this file, decides
whether the draft is right.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .cobol_num import edited_supported
from .cobol_src import normalize
from .model import ROOT, ProgramModel, load_model

VERBS = {
    "MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "IF", "EVALUATE", "PERFORM", "WRITE", "READ", "OPEN",
    "CLOSE", "DISPLAY", "INITIALIZE", "CONTINUE", "EXIT", "STOP", "GO", "GOBACK", "SET", "ACCEPT", "STRING", "UNSTRING",
    "INSPECT", "CALL", "NEXT", "REWRITE", "DELETE", "START", "RETURN", "RELEASE", "SORT", "MERGE", "CANCEL", "ALTER",
    "ENTRY", "EXEC", "SEARCH",
}
ENDERS = {"ELSE", "END-IF", "WHEN", "END-EVALUATE", "END-PERFORM", "END-COMPUTE", "END-ADD", "END-SUBTRACT", "END-MULTIPLY",
          "END-DIVIDE", "END-READ", "END-WRITE", "END-STRING", "END-CALL", "END-SEARCH"}
FIGURATIVE = {"SPACE": "S.SPACE", "SPACES": "S.SPACE", "ZERO": "S.ZERO", "ZEROS": "S.ZERO", "ZEROES": "S.ZERO",
              "HIGH-VALUE": "S.HIGH", "HIGH-VALUES": "S.HIGH", "LOW-VALUE": "S.LOW", "LOW-VALUES": "S.LOW",
              "QUOTE": "S.QUOTE", "QUOTES": "S.QUOTE"}
RESERVED = VERBS | ENDERS | set(FIGURATIVE) | {
    "TO", "FROM", "BY", "INTO", "GIVING", "ROUNDED", "ON", "NOT", "SIZE", "ERROR", "AT", "END", "THEN", "AND", "OR", "IS",
    "OTHER", "THRU", "THROUGH", "TIMES", "UNTIL", "VARYING", "WITH", "TEST", "BEFORE", "AFTER", "TRUE", "FALSE", "OF", "IN",
    "EQUAL", "GREATER", "LESS", "THAN", "POSITIVE", "NEGATIVE", "NUMERIC", "ALPHABETIC", "REMAINDER", "CORRESPONDING",
    "CORR", "ADVANCING", "LINE", "LINES", "PAGE", "RECORD", "INPUT", "OUTPUT", "I-O", "EXTEND", "RUN", "ALSO", "ALL",
    "FUNCTION", "UPON", "NO", "REPLACING", "INVALID", "KEY", "PARAGRAPH", "SECTION", "PROGRAM",
}


class Unsupported(Exception):
    pass


@dataclass
class Tok:
    kind: str  # word, str, num, op, end
    value: str
    line: int


_TOKEN = re.compile(
    r"""(?P<ws>[\s,;]+)
      | (?P<str>"(?:[^"]|"")*"|'(?:[^']|'')*')
      | (?P<num>\d+\.\d+|\.\d+|\d+(?![A-Za-z0-9_-]))
      | (?P<op>\*\*|>=|<=|<>|[()+\-*/=<>:])
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
            elif kind == "word":
                value = value.upper()
            out.append(Tok(kind, value, line))
    if out and out[-1].kind != "end":
        out.append(Tok("end", ".", out[-1].line))
    return out


def tokenize(sentences: list[tuple[int, str]]) -> list[Tok]:
    out: list[Tok] = []
    for line, text in sentences:
        pos = 0
        while pos < len(text):
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
            elif kind == "word":
                value = value.upper()
            out.append(Tok(kind, value, line))
        out.append(Tok("end", ".", line))
    return out


# ---------------------------------------------------------------- data items

_PIC_REPEAT = re.compile(r"([9XSVAZB0*$+\-,./])\((\d+)\)")


def _expand(pic: str) -> str:
    return _PIC_REPEAT.sub(lambda m: m.group(1) * int(m.group(2)), pic)


def _literal(tok_text: str):
    t = tok_text.strip()
    up = t.upper()
    if up in FIGURATIVE:
        return FIGURATIVE[up]
    if (t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"')):
        q = t[0]
        return t[1:-1].replace(q + q, q)
    try:
        return Decimal(t)
    except Exception:
        return None


@dataclass
class DataModel:
    items: dict[str, tuple] = field(default_factory=dict)  # name -> Item spec for runtime
    conds: dict[str, tuple[str, list]] = field(default_factory=dict)
    bad: dict[str, str] = field(default_factory=dict)  # name -> why it cannot be used


_VALUE_TOKENS = re.compile(r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|[^\s]+")


def parse_data(entries: list[tuple[int, str]], dm: DataModel) -> None:
    """Lenient parser for FD and WORKING-STORAGE entries: groups, PICs, VALUE, level 88."""
    stack: list[tuple[int, str]] = []  # (level, group name)
    last_elem = ""
    for line, text in entries:
        m = re.match(r"^\s*(\d{1,2})\s+([A-Z0-9][A-Z0-9-]*)(.*)$", text, re.S | re.I)
        if not m:
            continue
        level, name, rest = int(m.group(1)), m.group(2).upper(), m.group(3)
        if level == 88:
            target = last_elem
            vm = re.search(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?(.*)$", rest, re.I | re.S)
            if target and vm:
                toks = _VALUE_TOKENS.findall(vm.group(1))
                choices, i = [], 0
                while i < len(toks):
                    lo = _literal(toks[i])
                    hi = None
                    if i + 2 < len(toks) and toks[i + 1].upper() in ("THRU", "THROUGH"):
                        hi = _literal(toks[i + 2])
                        i += 2
                    if lo is not None:
                        choices.append((lo, hi))
                    i += 1
                dm.conds[name] = (target, choices)
            continue
        if level in (66, 77, 78) and level != 77:
            continue
        if level == 77:
            level = 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        if name == "FILLER":
            name = f"FILLER-{line}-{len(dm.items)}"
        upper = rest.upper()
        if re.search(r"\b(OCCURS|REDEFINES)\b", upper):
            dm.bad[name] = "uses OCCURS or REDEFINES"
            continue
        pic = re.search(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", rest, re.I)
        vm = re.search(r"\bVALUE\s+(?:IS\s+)?(\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|\S+)", rest, re.I)
        initial = _literal(vm.group(1)) if vm else None
        if not pic:
            dm.items[name] = ("group", 0, 0, False, 0, "", None, [])
            stack.append((level, name))
            if parent:
                dm.items[parent][7].append(name)
            continue
        p = _expand(pic.group(1).upper().rstrip("."))
        if re.search(r"\bCOMP-[12]\b|\bCOMPUTATIONAL-[12]\b|\bPOINTER\b|\bINDEX\b", upper):
            dm.bad[name] = "is a floating-point or pointer item"
            continue
        if re.fullmatch(r"[XA9]+", p) and re.search(r"[XA]", p):
            spec = ["alpha", 0, 0, False, len(p), p]
        elif re.fullmatch(r"(S?)(9*)(?:V(9+))?", p) and "9" in p:
            nm = re.fullmatch(r"(S?)(9*)(?:V(9+))?", p)
            ints, decs = len(nm.group(2)), len(nm.group(3) or "")
            sep = 1 if re.search(r"SIGN\s+(?:IS\s+)?(?:LEADING|TRAILING)\s+SEPARATE", upper) else 0
            spec = ["num", ints + decs, decs, bool(nm.group(1)), ints + decs + sep, p]
        elif edited_supported(p):
            spec = ["edited", 0, 0, False, len(p) - p.count("V"), p]
        else:
            dm.bad[name] = f"has an unsupported picture {pic.group(1)}"
            continue
        dm.items[name] = (*spec, initial, [])
        if parent:
            dm.items[parent][7].append(name)
        last_elem = name


# ---------------------------------------------------------------- parser

@dataclass
class Node:
    kind: str
    line: int
    data: dict = field(default_factory=dict)


class Parser:
    def __init__(self, toks: list[Tok], dm: DataModel, paragraphs: set[str]):
        self.t, self.i, self.dm, self.paras = toks, 0, dm, paragraphs

    # -- helpers
    def peek(self, k: int = 0) -> Tok:
        j = self.i + k
        return self.t[j] if j < len(self.t) else Tok("end", ".", self.t[-1].line if self.t else 0)

    def word(self, k: int = 0) -> str:
        tok = self.peek(k)
        return tok.value if tok.kind == "word" else ""

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

    # -- identifiers and operands
    def ident(self) -> str:
        tok = self.peek()
        if tok.kind != "word" or tok.value in RESERVED:
            raise Unsupported(f"expected a data name near {tok.value!r}")
        self.i += 1
        name = tok.value
        while self.word() in ("OF", "IN"):
            self.i += 2  # qualification: the first name is unique enough for these programs
        if self.peek().kind == "op" and self.peek().value == "(":
            raise Unsupported(f"{name}: subscripts and reference modification are not supported yet")
        if name in self.dm.bad:
            raise Unsupported(f"{name} {self.dm.bad[name]}")
        if name not in self.dm.items and name not in self.dm.conds:
            raise Unsupported(f"unknown data item {name}")
        return name

    def is_ident(self, k: int = 0) -> bool:
        tok = self.peek(k)
        return tok.kind == "word" and tok.value not in RESERVED and (tok.value in self.dm.items or tok.value in self.dm.bad)

    def value(self) -> str:
        """A MOVE source or comparison operand: identifier, literal or figurative constant (Python text)."""
        tok = self.peek()
        if tok.kind == "word" and tok.value == "ALL":
            raise Unsupported("ALL literals are not supported yet")
        if tok.kind == "word" and tok.value in FIGURATIVE:
            self.i += 1
            return FIGURATIVE[tok.value]
        if tok.kind == "str":
            self.i += 1
            return repr(tok.value)
        if tok.kind == "num":
            self.i += 1
            return f'D("{tok.value}")'
        if tok.kind == "op" and tok.value in "+-" and self.peek(1).kind == "num":
            self.i += 2
            return f'D("{tok.value}{self.t[self.i - 1].value}")'
        if tok.kind == "word" and tok.value == "FUNCTION":
            raise Unsupported("intrinsic FUNCTIONs are not supported yet")
        return f'S["{self.ident()}"]'

    def operand_num(self) -> str:
        tok = self.peek()
        if tok.kind == "num":
            self.i += 1
            return f'D("{tok.value}")'
        if tok.kind == "op" and tok.value in "+-" and self.peek(1).kind == "num":
            self.i += 2
            return f'D("{tok.value}{self.t[self.i - 1].value}")'
        if tok.kind == "word" and tok.value in ("ZERO", "ZEROS", "ZEROES"):
            self.i += 1
            return 'D("0")'
        return f'S.n("{self.ident()}")'

    # -- arithmetic expressions
    def expr(self) -> str:
        left = self.term()
        while self.peek().kind == "op" and self.peek().value in "+-" and len(self.peek().value) == 1:
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
        if self.peek().kind == "op" and self.peek().value == "**":
            self.i += 1
            return f"{base} ** {self.factor()}"
        return base

    def unary(self) -> str:
        tok = self.peek()
        if tok.kind == "op" and tok.value in "+-":
            self.i += 1
            return f"({tok.value}{self.unary()})"
        if tok.kind == "op" and tok.value == "(":
            self.i += 1
            inner = self.expr()
            if not (self.peek().kind == "op" and self.peek().value == ")"):
                raise Unsupported("unbalanced parentheses")
            self.i += 1
            return f"({inner})"
        return self.operand_num()

    # -- conditions
    def relop(self):
        """Returns a Python comparison operator or None, consuming the COBOL relational operator."""
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

    def comparand(self) -> str:
        """Operand of a relation: a plain value keeps its type (text or number); arithmetic is numeric."""
        save = self.i
        tok = self.peek()
        simple_next = self.peek(1)
        if tok.kind in ("str",) or (tok.kind == "word" and tok.value in FIGURATIVE):
            return self.value()
        if (tok.kind == "word" or tok.kind == "num") and not (simple_next.kind == "op" and simple_next.value in ("+", "-", "*", "/", "**")):
            return self.value()
        self.i = save
        return self.expr()

    def condition(self) -> str:
        self._last = None  # (subject, op) for abbreviated combined conditions
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
        return " and ".join(parts) if len(parts) > 1 else parts[0]

    def cond_not(self) -> str:
        if self.word() == "NOT" and self.relop_ahead(1) is False:
            self.i += 1
            return f"not ({self.cond_not()})"
        return self.cond_primary()

    def relop_ahead(self, k: int) -> bool:
        tok = self.peek(k)
        return (tok.kind == "op" and tok.value in ("=", ">", "<", ">=", "<=", "<>")) or (tok.kind == "word" and tok.value in ("EQUAL", "GREATER", "LESS"))

    def cond_primary(self) -> str:
        # abbreviated combined condition: "... AND > 5" or "... OR 7"
        if self._last and (self.relop_ahead(0) or (self.word() == "NOT" and self.relop_ahead(1))):
            subject = self._last[0]
            op = self.relop()
            obj = self.comparand()
            self._last = (subject, op)
            return f'S.cmp({subject}, "{op}", {obj})'
        tok = self.peek()
        if tok.kind == "word" and tok.value in self.dm.conds and not self.relop_ahead(1):
            self.i += 1
            return f'S.cond("{tok.value}")'
        if tok.kind == "op" and tok.value == "(":
            save = self.i
            try:
                return self.relation()
            except Unsupported:
                self.i = save + 1
                inner = self.cond_or()
                if not (self.peek().kind == "op" and self.peek().value == ")"):
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
        if cls in ("POSITIVE", "NEGATIVE", "ZERO", "NUMERIC"):
            self.i += 1
            num = subject.replace("S[", "S.n(").replace('"]', '")') if subject.startswith("S[") else subject
            test = {"POSITIVE": f"{num} > 0", "NEGATIVE": f"{num} < 0", "ZERO": f"{num} == 0",
                    "NUMERIC": f'S.is_numeric({subject[2:-1]})' if subject.startswith("S[") else "True"}[cls]
            return f"not ({test})" if negate else test
        self.i = save
        op = self.relop()
        if op is None:
            raise Unsupported(f"expected a comparison near {self.peek().value!r}")
        obj = self.comparand()
        self._last = (subject, op)
        return f'S.cmp({subject}, "{op}", {obj})'

    # -- statements
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
                while not self.at_boundary(stop):
                    self.i += 1
                text = " ".join(t.value if t.kind != "str" else repr(t.value) for t in self.t[start:self.i])
                nodes.append(Node("unsupported", tok.line, {"text": text, "why": str(exc)}))

    def statement(self, stop: set[str]) -> Node:
        tok = self.take()
        verb, line = tok.value, tok.line
        handler = getattr(self, "s_" + verb.replace("-", "_"), None)
        if handler is None:
            raise Unsupported(f"{'GO TO' if verb == 'GO' else verb} is not supported yet")
        return handler(line, stop)

    def size_phrases(self, stop: set[str], end_word: str) -> tuple[list[Node] | None, list[Node] | None]:
        on_err = not_err = None
        inner = stop | {"NOT", end_word}
        if self.word() in ("ON", "SIZE"):
            self.accept("ON")
            self.expect("SIZE")
            self.expect("ERROR")
            on_err = self.block(inner)
        if self.word() == "NOT" and self.word(1) in ("ON", "SIZE"):
            self.i += 1
            self.accept("ON")
            self.expect("SIZE")
            self.expect("ERROR")
            not_err = self.block(inner)
        self.accept(end_word)
        return on_err, not_err

    def targets(self, allow_rounded: bool = True) -> list[tuple[str, bool]]:
        out = []
        while self.is_ident():
            name = self.ident()
            rounded = allow_rounded and self.accept("ROUNDED")
            out.append((name, rounded))
        if not out:
            raise Unsupported(f"expected a receiving field near {self.peek().value!r}")
        return out

    def s_MOVE(self, line, stop):
        if self.word() in ("CORRESPONDING", "CORR"):
            raise Unsupported("MOVE CORRESPONDING is not supported yet")
        src = self.value()
        self.expect("TO")
        names = [n for n, _ in self.targets(allow_rounded=False)]
        return Node("move", line, {"src": src, "targets": names})

    def s_COMPUTE(self, line, stop):
        tg = self.targets()
        if self.peek().kind == "op" and self.peek().value == "=":
            self.i += 1
        elif not self.accept("EQUAL"):
            raise Unsupported("expected = in COMPUTE")
        e = self.expr()
        on_err, not_err = self.size_phrases(stop, "END-COMPUTE")
        return Node("compute", line, {"specs": [(n, e, r) for n, r in tg], "on_err": on_err, "not_err": not_err})

    def _operands(self, until: set[str]) -> list[str]:
        out = []
        while self.word() not in until and not self.peek().kind == "end":
            out.append(self.operand_num())
        if not out:
            raise Unsupported("expected operands")
        return out

    def s_ADD(self, line, stop):
        if self.word() in ("CORRESPONDING", "CORR"):
            raise Unsupported("ADD CORRESPONDING is not supported yet")
        ops = self._operands({"TO", "GIVING"})
        total = " + ".join(ops)
        if self.accept("TO"):
            dests = self.targets()
            if self.accept("GIVING"):
                base = " + ".join([total] + [f'S.n("{n}")' for n, _ in dests])
                specs = [(n, base, r) for n, r in self.targets()]
            else:
                specs = [(n, f'S.n("{n}") + {total}', r) for n, r in dests]
        else:
            self.expect("GIVING")
            specs = [(n, total, r) for n, r in self.targets()]
        on_err, not_err = self.size_phrases(stop, "END-ADD")
        return Node("compute", line, {"specs": specs, "on_err": on_err, "not_err": not_err})

    def s_SUBTRACT(self, line, stop):
        ops = self._operands({"FROM"})
        total = " + ".join(ops)
        self.expect("FROM")
        dests = self.targets()
        if self.accept("GIVING"):
            if len(dests) != 1:
                raise Unsupported("SUBTRACT ... FROM several fields GIVING is not supported")
            specs = [(n, f'S.n("{dests[0][0]}") - ({total})', r) for n, r in self.targets()]
        else:
            specs = [(n, f'S.n("{n}") - ({total})', r) for n, r in dests]
        on_err, not_err = self.size_phrases(stop, "END-SUBTRACT")
        return Node("compute", line, {"specs": specs, "on_err": on_err, "not_err": not_err})

    def s_MULTIPLY(self, line, stop):
        a = self.operand_num()
        self.expect("BY")
        if self.accept("GIVING"):
            raise Unsupported("malformed MULTIPLY")
        if self.is_ident() and self.word(1) != "GIVING":
            dests = self.targets()
            if self.accept("GIVING"):
                specs = [(n, f'{a} * S.n("{dests[0][0]}")', r) for n, r in self.targets()]
            else:
                specs = [(n, f'{a} * S.n("{n}")', r) for n, r in dests]
        else:
            b = self.operand_num()
            self.expect("GIVING")
            specs = [(n, f"{a} * {b}", r) for n, r in self.targets()]
        on_err, not_err = self.size_phrases(stop, "END-MULTIPLY")
        return Node("compute", line, {"specs": specs, "on_err": on_err, "not_err": not_err})

    def s_DIVIDE(self, line, stop):
        a = self.operand_num()
        if self.accept("INTO"):
            if self.is_ident() and self.word(1) != "GIVING":
                dests = self.targets()
                if self.accept("GIVING"):
                    specs = [(n, f'S.n("{dests[0][0]}") / {a}', r) for n, r in self.targets()]
                else:
                    specs = [(n, f'S.n("{n}") / {a}', r) for n, r in dests]
            else:
                b = self.operand_num()
                self.expect("GIVING")
                specs = [(n, f"{b} / {a}", r) for n, r in self.targets()]
        else:
            self.expect("BY")
            b = self.operand_num()
            self.expect("GIVING")
            specs = [(n, f"{a} / {b}", r) for n, r in self.targets()]
        if self.word() == "REMAINDER":
            raise Unsupported("DIVIDE ... REMAINDER is not supported yet")
        on_err, not_err = self.size_phrases(stop, "END-DIVIDE")
        return Node("compute", line, {"specs": specs, "on_err": on_err, "not_err": not_err})

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
        if self.accept("TRUE"):
            subject = None
        else:
            subject = self.comparand()
        if self.word() == "ALSO":
            raise Unsupported("EVALUATE ... ALSO is not supported yet")
        branches = []
        while self.accept("WHEN"):
            conds = []
            while True:
                if self.accept("OTHER"):
                    conds = None
                    break
                if subject is None:
                    self._last = None
                    conds.append(self.cond_or())
                else:
                    negate = self.accept("NOT")
                    lo = self.comparand()
                    if self.accept("THRU", "THROUGH"):
                        hi = self.comparand()
                        test = f'(S.cmp({subject}, ">=", {lo}) and S.cmp({subject}, "<=", {hi}))'
                    else:
                        test = f'S.cmp({subject}, "==", {lo})'
                    conds.append(f"not {test}" if negate else test)
                break  # consecutive WHENs become branches with empty bodies; the emitter merges them
            body = self.block(stop | {"WHEN", "END-EVALUATE"})
            branches.append((None if conds is None else " or ".join(f"({c})" for c in conds), body))
        self.accept("END-EVALUATE")
        return Node("evaluate", line, {"branches": branches})

    def s_PERFORM(self, line, stop):
        target = self.word()
        if target in self.paras:
            self.i += 1
            names = [target]
            if self.accept("THRU", "THROUGH"):
                names.append(self.take().value)
            mode = self.loop_mode()
            return Node("perform", line, {"paras": names, "mode": mode, "body": None})
        mode = self.loop_mode()
        body = self.block(stop | {"END-PERFORM"})
        self.expect("END-PERFORM")
        return Node("perform", line, {"paras": None, "mode": mode, "body": body})

    def loop_mode(self):
        if self.accept("WITH"):
            self.expect("TEST")
            after = self.accept("AFTER")
            if not after:
                self.expect("BEFORE")
            self.expect("UNTIL")
            return ("until", self.condition(), after)
        if self.accept("UNTIL"):
            return ("until", self.condition(), False)
        if self.accept("VARYING"):
            var = self.ident()
            self.expect("FROM")
            start = self.operand_num()
            self.expect("BY")
            step = self.operand_num()
            self.expect("UNTIL")
            cond = self.condition()
            if self.word() == "AFTER":
                raise Unsupported("PERFORM VARYING ... AFTER is not supported yet")
            return ("varying", var, start, step, cond)
        if (self.peek().kind == "num" or self.is_ident()) and self.word(1) == "TIMES":
            n = self.operand_num()
            self.expect("TIMES")
            return ("times", n)
        return ("once",)

    def s_READ(self, line, stop):
        file = self.take().value
        self.accept("NEXT")
        self.accept("RECORD")
        if self.accept("INTO"):
            raise Unsupported("READ ... INTO is not supported yet")
        at_end = not_at_end = None
        inner = stop | {"NOT", "END-READ"}
        if self.word() in ("AT", "END") and not (self.word() == "END" and self.word(1) == "-"):
            self.accept("AT")
            self.expect("END")
            at_end = self.block(inner)
        if self.word() == "NOT":
            self.i += 1
            self.accept("AT")
            self.expect("END")
            not_at_end = self.block(inner)
        self.accept("END-READ")
        return Node("read", line, {"file": file, "at_end": at_end or [], "not_at_end": not_at_end or []})

    def s_WRITE(self, line, stop):
        rec = self.take().value
        src = None
        if self.accept("FROM"):
            src = self.value()
        if self.word() in ("BEFORE", "AFTER"):
            self.i += 1
            self.accept("ADVANCING")
            if self.accept("PAGE"):
                pass
            else:
                self.take()
                self.accept("LINE", "LINES")
        self.accept("END-WRITE")
        return Node("write", line, {"record": rec, "from": src})

    def _skip_words(self, stop):
        while not self.at_boundary(stop):
            self.i += 1

    def s_OPEN(self, line, stop):
        self._skip_words(stop)
        return Node("noop", line, {"what": "OPEN"})

    def s_CLOSE(self, line, stop):
        self._skip_words(stop)
        return Node("noop", line, {"what": "CLOSE"})

    def s_DISPLAY(self, line, stop):
        self._skip_words(stop)
        return Node("noop", line, {"what": "DISPLAY (console output is not compared)"})

    def s_CONTINUE(self, line, stop):
        return Node("noop", line, {"what": "CONTINUE"})

    def s_EXIT(self, line, stop):
        if self.accept("PARAGRAPH", "SECTION"):
            return Node("return", line)
        if self.accept("PERFORM"):
            raise Unsupported("EXIT PERFORM is not supported yet")
        if self.accept("PROGRAM"):
            raise Unsupported("EXIT PROGRAM inside the record logic is not supported")
        return Node("noop", line, {"what": "EXIT"})

    def s_STOP(self, line, stop):
        self.accept("RUN")
        return Node("stop", line)

    def s_GOBACK(self, line, stop):
        return Node("stop", line)

    def s_INITIALIZE(self, line, stop):
        names = [n for n, _ in self.targets(allow_rounded=False)]
        if self.word() == "REPLACING":
            raise Unsupported("INITIALIZE ... REPLACING is not supported yet")
        return Node("initialize", line, {"names": names})

    def s_SET(self, line, stop):
        name = self.take().value
        if name in self.dm.conds and self.accept("TO") and self.accept("TRUE"):
            return Node("set_true", line, {"name": name})
        raise Unsupported("only SET condition-name TO TRUE is supported")


# ---------------------------------------------------------------- program structure

def split_paragraphs(toks: list[Tok]) -> tuple[list[str], dict[str, list[Tok]]]:
    """Paragraph headers are sentences made of one non-verb word (or NAME SECTION)."""
    order, paras = ["(start)"], {"(start)": []}
    current = "(start)"
    i = 0
    sentence: list[Tok] = []
    while i < len(toks):
        sentence.append(toks[i])
        if toks[i].kind == "end":
            words = [t for t in sentence if t.kind != "end"]
            is_header = (len(words) == 1 and words[0].kind == "word" and words[0].value not in VERBS and words[0].value not in ENDERS) or (
                len(words) == 2 and words[1].value == "SECTION")
            if words and words[0].value == "PROCEDURE":
                pass
            elif is_header:
                current = words[0].value
                order.append(current)
                paras[current] = []
            else:
                paras[current].extend(sentence)
            sentence = []
        i += 1
    if not paras["(start)"]:
        order.remove("(start)")
        del paras["(start)"]
    return order, paras


@dataclass
class Translation:
    program: str
    code: str
    statements: int
    unsupported: list[dict]
    record_paragraph: str


def _walk(nodes):
    for n in nodes or []:
        yield n
        for key in ("then", "else", "body", "on_err", "not_err", "at_end", "not_at_end"):
            sub = n.data.get(key) if n.data else None
            if isinstance(sub, list):
                yield from _walk(sub)
        if n.kind == "evaluate":
            for _, body in n.data["branches"]:
                yield from _walk(body)


def _is_read_only(nodes: list[Node], infile: str) -> bool:
    real = [n for n in nodes if n.kind != "noop"]
    return bool(real) and all(n.kind == "read" for n in real)


def _record_work(order, parsed, infile) -> tuple[list[Node], list[Node], str]:
    """Find (init statements, per-record statements, description) from the program's read loop."""
    read_paras = {p for p in order if _is_read_only(parsed[p], infile)}
    entry = order[0]

    def strip_reads(nodes: list[Node]) -> list[Node]:
        out = []
        for n in nodes:
            if n.kind == "read":
                if n.data["not_at_end"]:
                    out.extend(n.data["not_at_end"])
                continue
            if n.kind == "perform" and n.data["paras"] and all(p in read_paras for p in n.data["paras"]) and n.data["mode"][0] == "once":
                continue
            out.append(n)
        return out

    nodes = parsed[entry]
    for idx, n in enumerate(nodes):
        if n.kind == "perform" and n.data["mode"][0] in ("until", "varying"):
            init = [m for m in strip_reads(nodes[:idx]) if m.kind not in ("noop",)]
            if n.data["body"] is not None:
                body = strip_reads(n.data["body"])
                where = f"the loop at line {n.line}"
            else:
                body = []
                for p in n.data["paras"]:
                    body.extend(strip_reads(parsed[p]))
                where = f"paragraph {n.data['paras'][0]}"
            # the remaining work must not read again
            if any(m.kind == "read" for m in _walk(body)):
                raise Unsupported("the record loop reads in more than one place")
            return init, body, where
    raise Unsupported("no PERFORM ... UNTIL read loop found in the first paragraph")


# ---------------------------------------------------------------- emitter

class Emitter:
    def __init__(self, paras: dict[str, list[Node]], order: list[str], out_record: str):
        self.paras, self.order, self.out_record = paras, order, out_record
        self.used: set[str] = set()
        self.unsupported: list[dict] = []
        self.count = 0

    @staticmethod
    def fname(p: str) -> str:
        return "p_" + re.sub(r"[^a-z0-9_]", "_", p.lower().replace("-", "_"))

    def lines(self, nodes: list[Node], ind: int) -> list[str]:
        pad = "    " * ind
        out: list[str] = []
        for n in nodes:
            self.count += n.kind not in ("noop",)
            tag = f"  # L{n.line}"
            k, d = n.kind, n.data
            if k == "move":
                out.append(f'{pad}S.move({d["src"]}, {", ".join(repr(t) for t in d["targets"])}){tag}')
            elif k == "compute":
                specs = ", ".join(f'("{name}", lambda: {e}, {r})' for name, e, r in d["specs"])
                guarded = d["on_err"] is not None or d["not_err"] is not None
                call = f"S.compute([{specs}], guarded={guarded})"
                if not guarded:
                    out.append(f"{pad}{call}{tag}")
                else:
                    out.append(f"{pad}if not {call}:{tag}")
                    out += self.lines(d["on_err"] or [], ind + 1) or [pad + "    pass"]
                    if d["not_err"]:
                        out.append(f"{pad}else:")
                        out += self.lines(d["not_err"], ind + 1) or [pad + "    pass"]
            elif k == "if":
                out.append(f"{pad}if {d['cond']}:{tag}")
                out += self.lines(d["then"], ind + 1) or [pad + "    pass"]
                if d["else"]:
                    out.append(f"{pad}else:")
                    out += self.lines(d["else"], ind + 1) or [pad + "    pass"]
            elif k == "evaluate":
                first = True
                merged = []
                for cond, body in d["branches"]:  # consecutive WHENs with no body share the next body
                    if merged and not merged[-1][1] and merged[-1][0] is not None and cond is not None:
                        merged[-1] = (f"{merged[-1][0]} or {cond}", body)
                    else:
                        merged.append((cond, body))
                for cond, body in merged:
                    if cond is None:
                        out.append(f"{pad}{'else' if not first else 'if True'}:{tag if first else ''}")
                    else:
                        out.append(f"{pad}{'if' if first else 'elif'} {cond}:{tag if first else ''}")
                    out += self.lines(body, ind + 1) or [pad + "    pass"]
                    first = False
            elif k == "perform":
                out += self.perform(n, ind)
            elif k == "write":
                if d["from"]:
                    out.append(f'{pad}S.move({d["from"]}, "{d["record"]}"){tag}')
                out.append(f'{pad}S.write("{d["record"]}"){tag}')
            elif k == "initialize":
                out.append(f'{pad}S.initialize({", ".join(repr(x) for x in d["names"])}){tag}')
            elif k == "set_true":
                out.append(f'{pad}S.set_true("{d["name"]}"){tag}')
            elif k == "return":
                out.append(f"{pad}return{tag}")
            elif k == "noop":
                out.append(f"{pad}pass{tag} {d['what']}")
            elif k == "stop":
                self.unsupported.append({"line": n.line, "text": "STOP RUN", "why": "STOP RUN inside the record logic"})
                out.append(f'{pad}S.unsupported("line {n.line}: STOP RUN inside the record logic"){tag}')
            elif k == "read":
                self.unsupported.append({"line": n.line, "text": f"READ {d['file']}", "why": "a READ inside the record logic"})
                out.append(f'{pad}S.unsupported("line {n.line}: READ inside the record logic"){tag}')
            elif k == "unsupported":
                self.unsupported.append({"line": n.line, "text": d["text"], "why": d["why"]})
                note = d["text"][:70].replace("\\", "/").replace('"', "'")
                out.append(f'{pad}S.unsupported("line {n.line}: {note}"){tag} {d["why"]}')
        return out

    def perform(self, n: Node, ind: int) -> list[str]:
        pad = "    " * ind
        d = n.data
        tag = f"  # L{n.line}"
        if d["paras"]:
            names = d["paras"]
            if len(names) == 2:
                a, b = self.order.index(names[0]), self.order.index(names[1])
                names = self.order[a : b + 1]
            for p in names:
                self.used.add(p)
            calls = [f"{self.fname(p)}()" for p in names]
        else:
            calls = None
        mode = d["mode"]
        out: list[str] = []
        body_ind = ind
        if mode[0] == "once":
            pass
        elif mode[0] == "times":
            out.append(f"{pad}for _ in range(int({mode[1]})):{tag}")
            body_ind += 1
        elif mode[0] == "until":
            if mode[2]:  # test after
                out.append(f"{pad}for _ in S.loop():{tag}")
                body_ind += 1
            else:
                out.append(f"{pad}for _ in S.loop():{tag}")
                out.append(f"{pad}    if {mode[1]}:")
                out.append(f"{pad}        break")
                body_ind += 1
        elif mode[0] == "varying":
            _, var, start, step, cond = mode
            out.append(f'{pad}S.compute([("{var}", lambda: {start}, False)]){tag}')
            out.append(f"{pad}for _ in S.loop():")
            out.append(f"{pad}    if {cond}:")
            out.append(f"{pad}        break")
            body_ind += 1
        bpad = "    " * body_ind
        if calls:
            out += [f"{bpad}{c}{tag if mode[0] == 'once' else ''}" for c in calls]
        else:
            out += self.lines(d["body"], body_ind) or [bpad + "pass"]
        if mode[0] == "until" and mode[2]:
            out.append(f"{bpad}if {mode[1]}:")
            out.append(f"{bpad}    break")
        if mode[0] == "varying":
            out.append(f'{bpad}S.compute([("{mode[1]}", lambda: S.n("{mode[1]}") + {mode[3]}, False)])')
        return out


def _items_literal(dm: DataModel) -> str:
    def lit(v):
        if isinstance(v, Decimal):
            return f'D("{v}")'
        if isinstance(v, str) and v.startswith("S."):
            return {"S.SPACE": "SPACE", "S.ZERO": "ZERO", "S.HIGH": "HIGH", "S.LOW": "LOW", "S.QUOTE": "QUOTE"}[v]
        return repr(v)

    rows = []
    for name, (kind, digits, scale, signed, width, pic, init, children) in dm.items.items():
        rows.append(f'    "{name}": ("{kind}", {digits}, {scale}, {signed}, {width}, {pic!r}, {lit(init)}, {children!r}),')
    conds = []
    for name, (var, choices) in dm.conds.items():
        conds.append(f'    "{name}": ("{var}", [{", ".join(f"({lit(lo)}, {lit(hi)})" for lo, hi in choices)}]),')
    return "ITEMS = {\n" + "\n".join(rows) + "\n}\n\nCONDITIONS = {\n" + "\n".join(conds) + "\n}\n"


def translate(program: str, root: Path = ROOT) -> Translation:
    model: ProgramModel = load_model(program, root)
    dm = DataModel()
    for fd in (model.input.name, model.output.name):
        parse_data(model.fd_items.get(fd, []), dm)
    parse_data(model.ws_items, dm)
    for layout in (model.in_layout, model.out_layout):
        for f in layout.fields:
            if f.name != "FILLER" and f.name not in dm.items:
                raise Unsupported(f"record field {f.name} was not found in the data descriptions")
    src_lines = normalize(model.path.read_text(encoding="utf-8", errors="replace"), model.fixed)
    start = next((i for i, l in enumerate(src_lines) if not l.comment and re.match(r"^\s*PROCEDURE\s+DIVISION", l.text, re.I)), None)
    if start is None:
        raise Unsupported("no PROCEDURE DIVISION")
    proc_lines = src_lines[start + 1:]
    if any(not l.comment and re.match(r"^\s*COPY\s", l.text, re.I) for l in proc_lines):
        raise Unsupported("COPY inside the PROCEDURE DIVISION is not supported yet")
    toks = tokenize_lines(proc_lines)
    order, ptoks = split_paragraphs(toks)
    names = set(order)
    parsed: dict[str, list[Node]] = {}
    # a paragraph holds several sentences and Parser.block stops at each '.', so parse sentence by sentence
    for p in order:
        parser = Parser(ptoks[p], dm, names)
        nodes: list[Node] = []
        while parser.i < len(parser.t):
            nodes += parser.block(set())
            if parser.peek().kind == "end":
                parser.i += 1
            elif parser.i < len(parser.t):  # a stray END-x or ELSE at sentence level
                tok = parser.take()
                nodes.append(Node("unsupported", tok.line, {"text": tok.value, "why": f"unexpected {tok.value}"}))
        parsed[p] = nodes
    init, body, where = _record_work(order, parsed, model.input.name)

    out_record = model.out_layout.record_name
    em = Emitter(parsed, order, out_record)
    init_lines = em.lines(init, 1)
    body_lines = em.lines(body, 1)
    funcs: list[str] = []
    done: set[str] = set()
    while em.used - done:
        for p in [p for p in order if p in em.used and p not in done]:
            done.add(p)
            src_lines = em.lines(parsed[p], 1)
            funcs.append(f"def {em.fname(p)}():  # paragraph {p}\n" + "\n".join(src_lines or ["    pass"]) + "\n")

    in_map = [(f.py_name, f.name) for f in model.in_layout.fields if f.name != "FILLER"]
    out_map = [(f.py_name, f.name) for f in model.out_layout.fields if f.name != "FILLER"]
    total = em.count
    gaps = em.unsupported
    header = (
        f'"""Draft Python for legacy/{program}/{program}.cbl (PROGRAM-ID {model.program_id}).\n\n'
        f"Written by the Séance translator on {_dt.date.today().isoformat()}. Each line is tagged with the COBOL line it\n"
        f"came from. The per-record logic is {where}.\n"
        + (f"{len(gaps)} statement(s) could not be translated; they raise NotImplementedError naming the line:\n"
           + "".join(f"  - line {g['line']}: {g['text'][:60]} ({g['why']})\n" for g in gaps)
           if gaps else "Every statement was translated.\n")
        + 'This file is yours now: edit it, then run the check.\n"""\n'
    )
    code = (
        header
        + "\nfrom decimal import Decimal as D\n\n"
        + f"from generated.{program}_records import InRecord, OutRecord\n"
        + "from seance.runtime import HIGH, LOW, QUOTE, SPACE, ZERO, Store\n\n"
        + _items_literal(dm)
        + f"\nIN_FIELDS = {in_map!r}\nOUT_FIELDS = {out_map!r}\n\nS = Store(ITEMS, CONDITIONS)\n\n\n"
        + "def reset():\n    \"\"\"Run once per input file, like the COBOL start-up code before the read loop.\"\"\"\n    S.reset()\n    S.started = True\n"
        + ("\n".join(init_lines) + "\n" if init_lines else "")
        + "\n\n"
        + "\n\n".join(funcs)
        + ("\n\n" if funcs else "")
        + "def one_record():\n    \"\"\"The work the COBOL does for each record it reads.\"\"\"\n"
        + ("\n".join(body_lines) if body_lines else "    pass")
        + "\n\n\ndef transform(rec: InRecord) -> OutRecord:\n"
        + "    if not S.started:\n        reset()\n    S.load(rec, IN_FIELDS)\n    S.written.clear()\n    one_record()\n    return S.output(OutRecord, OUT_FIELDS)\n"
    )
    compile(code, f"migrated/{program}.py", "exec")  # never hand the user a draft that does not parse
    return Translation(program, code, total, gaps, where)


def write_draft(program: str, root: Path = ROOT, overwrite: bool = False) -> tuple[Path, Translation]:
    tr = translate(program, root)
    target = root / "migrated" / f"{program}.py"
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target.relative_to(root).as_posix()} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    (target.parent / "__init__.py").touch()
    target.write_text(tr.code, encoding="utf-8")
    return target, tr
