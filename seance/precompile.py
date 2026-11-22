"""What the compiler does to the text before it reads the program, done the same way here so the data layout,
the translator and the analysis all see the program GnuCOBOL compiles.

* Compiler directives: >>DEFINE, >>IF / >>ELIF / >>ELSE / >>END-IF (with IS [NOT] DEFINED, comparisons, AND, OR,
  NOT), >>SET CONSTANT. Other directives (>>TURN, >>PAGE, >>LISTING, $SET ...) change nothing the program computes
  here and are dropped.
* COPY and REPLACE are done before this pass, the way cobc does them (seance.copybook).
* Named constants: level 78 items, 01 name CONSTANT AS value, >>DEFINE CONSTANT. Each use is replaced by its value.

Lines keep their numbers, so every message and every # Lnn tag still points at the original source.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

WORD = r"[A-Za-z0-9][A-Za-z0-9_-]*"
_EDGE_L, _EDGE_R = r"(?<![A-Za-z0-9_-])", r"(?![A-Za-z0-9_-])"
_TOKEN = re.compile(r"\s*(>=|<=|<>|[=<>()]|'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[+-]?\d+(?:\.\d+)?|" + WORD + r")", re.I)



# ---------------------------------------------------------------- outside quotes

def _split_quotes(text: str) -> list[tuple[bool, str]]:
    """(is_literal, piece) parts of a line, so substitutions never touch the inside of a literal."""
    parts, i, start, quote = [], 0, 0, ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                parts.append((True, text[start:i + 1]))
                start, quote = i + 1, ""
        elif ch in "'\"":
            if i > start:
                parts.append((False, text[start:i]))
            start, quote = i, ch
        i += 1
    if start < len(text):
        parts.append((bool(quote), text[start:]))
    return parts


def _outside_quotes(text: str, fn) -> str:
    return "".join(piece if lit else fn(piece) for lit, piece in _split_quotes(text))


# ---------------------------------------------------------------- >>IF conditions

def _value(tok: str, defs: dict[str, str | None]):
    if tok[:1] in "'\"":
        return tok[1:-1]
    try:
        return Decimal(tok)
    except InvalidOperation:
        v = defs.get(tok.upper())
        if v is None:
            return None
        try:
            return Decimal(v)
        except InvalidOperation:
            return v.strip("'\"")


def evaluate(cond: str, defs: dict[str, str | None]) -> bool:
    """True when a >>IF condition holds. An unknown form counts as false, as an undefined name would."""
    toks = [m.group(1) for m in _TOKEN.finditer(cond)]
    pos = 0

    def peek(k=0):
        return toks[pos + k].upper() if pos + k < len(toks) else ""

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def expr():
        left = term()
        while peek() == "OR":
            take()
            left = term() or left
        return left

    def term():
        left = factor()
        while peek() == "AND":
            take()
            right = factor()
            left = left and right
        return left

    def factor():
        if peek() == "NOT":
            take()
            return not factor()
        if peek() == "(":
            take()
            v = expr()
            if peek() == ")":
                take()
            return v
        a = take() if pos < len(toks) else ""
        if peek() == "IS":
            take()
        negate = False
        if peek() == "NOT":
            take()
            negate = True
        if peek() == "DEFINED":
            take()
            return (a.upper() in defs) != negate
        if peek() in ("=", "<>", ">", "<", ">=", "<=", "EQUAL", "GREATER", "LESS"):
            op = take().upper()
            if op in ("EQUAL", "GREATER", "LESS"):
                while peek() in ("TO", "THAN", "OR", "EQUAL"):
                    if peek() == "OR":
                        take()
                        take()
                        op = {"GREATER": ">=", "LESS": "<="}.get(op, op)
                    else:
                        take()
                op = {"EQUAL": "=", "GREATER": ">", "LESS": "<"}.get(op, op)
            b = take() if pos < len(toks) else ""
            x, y = _value(a, defs), _value(b, defs)
            if x is None or y is None:
                return negate
            if isinstance(x, Decimal) != isinstance(y, Decimal):
                x, y = str(x), str(y)
            r = {"=": x == y, "<>": x != y, ">": x > y, "<": x < y, ">=": x >= y, "<=": x <= y}[op]
            return r != negate
        return (a.upper() in defs) != negate  # a bare name: true when defined

    try:
        return bool(expr())
    except (IndexError, KeyError, TypeError):
        return False


# ---------------------------------------------------------------- constants

def _constant_value(raw: str, consts: dict[str, str]) -> str | None:
    """The text a constant stands for: a literal, a figurative constant, or arithmetic over numbers and other constants."""
    raw = raw.strip().rstrip(".").strip()
    if re.fullmatch(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[xX]'[0-9A-Fa-f]*'|[xX]\"[0-9A-Fa-f]*\"", raw):
        return raw
    if re.fullmatch(r"(?i)(ZEROS?|ZEROES|SPACES?|HIGH-VALUES?|LOW-VALUES?|QUOTES?|NULLS?)", raw):
        return raw.upper()
    if re.fullmatch(WORD, raw) and raw.upper() in consts:
        return consts[raw.upper()]  # a constant defined as another constant: a string stays a string
    expr = re.sub(WORD, lambda m: consts.get(m.group(0).upper(), m.group(0)), raw)
    if not re.fullmatch(r"[\d\s.+\-*/()]+", expr):
        return None
    try:
        value = _arith(expr)
    except (InvalidOperation, ZeroDivisionError, ValueError, IndexError):
        return None
    text = format(value.normalize(), "f") if value != value.to_integral_value() else str(int(value))
    return text


def _arith(expr: str) -> Decimal:
    toks = re.findall(r"\d+(?:\.\d+)?|[+\-*/()]", expr)
    pos = 0

    def atom():
        nonlocal pos
        t = toks[pos]
        pos += 1
        if t == "(":
            v = add()
            pos += 1
            return v
        if t == "-":
            return -atom()
        if t == "+":
            return atom()
        return Decimal(t)

    def mul():
        nonlocal pos
        v = atom()
        while pos < len(toks) and toks[pos] in "*/":
            op = toks[pos]
            pos += 1
            v = v * atom() if op == "*" else v / atom()
        return v

    def add():
        nonlocal pos
        v = mul()
        while pos < len(toks) and toks[pos] in "+-":
            op = toks[pos]
            pos += 1
            v = v + mul() if op == "+" else v - mul()
        return v

    v = add()
    if pos != len(toks):
        raise ValueError(expr)
    return v


_CONST_78 = re.compile(r"^\s*78\s+(" + WORD + r")\s+VALUE\s+(?:IS\s+)?(.+?)\s*\.?\s*$", re.I)
_CONST_01 = re.compile(r"^\s*0?1\s+(" + WORD + r")\s+CONSTANT\s+(?:AS\s+)?(.+?)\s*\.?\s*$", re.I)


# ---------------------------------------------------------------- DECIMAL-POINT IS COMMA

_PIC = re.compile(r"(?<![A-Za-z0-9-])(PIC(?:TURE)?\s+(?:IS\s+)?)(\S+)", re.I)
_SWAP = str.maketrans(".,", ",.")


def _comma_piece(piece: str) -> str:
    """Pictures get the standard roles of . and , back; 1,5 becomes 1.5. The period that ends an entry stays."""
    out, last = [], 0
    for m in _PIC.finditer(piece):
        out.append(re.sub(r"(?<![A-Za-z0-9-])([+-]?\d*),(\d+)(?![A-Za-z0-9-])", r"\1.\2", piece[last:m.start()]))
        pic, end = m.group(2), ""
        while pic.endswith("."):
            pic, end = pic[:-1], end + "."
        out.append(m.group(1) + pic.translate(_SWAP) + end)
        last = m.end()
    out.append(re.sub(r"(?<![A-Za-z0-9-])([+-]?\d*),(\d+)(?![A-Za-z0-9-])", r"\1.\2", piece[last:]))
    return "".join(out)


_CURRENCY = re.compile(r"\bCURRENCY\s+(?:SIGN\s+)?(?:IS\s+)?([\"'])(.+?)\1(?:\s+WITH\s+PICTURE\s+SYMBOL\s+([\"'])(.)\3)?", re.I)


def currency_symbol(text: str) -> str | None:
    """The picture symbol a CURRENCY SIGN clause chooses ("W" in CURRENCY SIGN IS "W"), or None."""
    m = _CURRENCY.search(text)
    if not m:
        return None
    return m.group(4) or (m.group(2) if len(m.group(2)) == 1 else None)


def currency_text(text: str) -> str | None:
    """What the program prints for its currency sign."""
    m = _CURRENCY.search(text)
    return m.group(2) if m else None


# ---------------------------------------------------------------- >>IF state

_DEFINE = re.compile(r"(?:(CONSTANT)\s+)?(" + WORD + r")(?:\s+AS\s+(.+?))?(?:\s+OVERRIDE)?\s*$", re.I)
_CONDITIONAL = {"IF", "ELIF", "ELSE-IF", "ELSE", "END-IF", "DEFINE", "SET"}


def directive(text: str) -> tuple[str, str] | None:
    """(word, rest) of a compiler directive line: >>IF X DEFINED gives ("IF", "X DEFINED"). None for code."""
    stripped = text.strip()
    if not (stripped.startswith(">>") or stripped.startswith("$")):
        return None
    m = re.match(r"(?:>>|\$)\s*([A-Z-]+)\s*(.*)$", stripped, re.I)
    return (m.group(1).upper(), m.group(2)) if m else ("", "")


class Conditions:
    """Which lines the compiler reads: the >>IF / >>ELIF / >>ELSE / >>END-IF state, and the names >>DEFINE sets."""

    def __init__(self) -> None:
        self.defs: dict[str, str | None] = {}
        self.stack: list[list[bool]] = []  # [this branch is taken, a branch of this >>IF was taken already]

    @property
    def active(self) -> bool:
        return all(s[0] for s in self.stack)

    def track(self, word: str, rest: str) -> re.Match | None:
        """Follow one directive. Returns the match of a >>DEFINE or >>SET that gave a name a value."""
        if word == "IF":
            cond = self.active and evaluate(rest, self.defs)
            self.stack.append([cond, cond])
        elif word in ("ELIF", "ELSE-IF") and self.stack:
            parent = all(s[0] for s in self.stack[:-1])
            cond = parent and not self.stack[-1][1] and evaluate(rest, self.defs)
            self.stack[-1] = [cond, self.stack[-1][1] or cond]
        elif word == "ELSE" and self.stack:
            parent = all(s[0] for s in self.stack[:-1])
            self.stack[-1] = [parent and not self.stack[-1][1], True]
        elif word == "END-IF" and self.stack:
            self.stack.pop()
        elif word in ("DEFINE", "SET") and self.active:
            dm = _DEFINE.match(rest)
            if dm:
                name, value = dm.group(2).upper(), dm.group(3)
                if value and value.strip().upper() == "OFF":
                    self.defs.pop(name, None)
                elif value and value.strip().upper() == "PARAMETER":
                    pass  # comes from the compile command line, which Séance does not set: stays undefined
                else:
                    self.defs[name] = value.strip() if value else None
                    return dm
        return None


# ---------------------------------------------------------------- the pass

def apply(lines: list, make_line, debugging: bool = False) -> tuple[list, list[str]]:
    """lines: Line objects (number, text, comment), with COPY and REPLACE already done (seance.copybook).
    make_line(number, text, comment) builds a new one. debugging: the program says WITH DEBUGGING MODE, so >>D
    lines are compiled. Returns the lines the compiler reads, and notes about what was done."""
    cond = Conditions()
    consts: dict[str, str] = {}
    const_rx: re.Pattern | None = None
    notes: set[str] = set()
    out = []
    comma = any(not ln.comment and re.search(r"\bDECIMAL-POINT\s+IS\s+COMMA\b", ln.text, re.I) for ln in lines)
    # CURRENCY SIGN IS "W": pictures get the standard $ back, and the runtime shows the program's own sign
    currency = currency_symbol(" ".join(ln.text for ln in lines if not ln.comment))

    def substitute(text: str) -> str:
        if const_rx is not None:
            text = _outside_quotes(text, lambda s: const_rx.sub(lambda m: consts[m.group(0).upper()], s))
        return text

    def remember(name: str, value: str) -> None:
        nonlocal const_rx
        consts[name] = value
        const_rx = re.compile(_EDGE_L + "(" + "|".join(re.escape(k) for k in sorted(consts, key=len, reverse=True)) + ")" + _EDGE_R, re.I)
        notes.add("constants")

    for ln in lines:
        if ln.comment:
            out.append(ln)
            continue
        d = directive(ln.text)
        if d is not None:
            word, rest = d
            if word == "D":  # a debugging line
                if debugging and cond.active and rest.strip():
                    out.append(make_line(ln.number, substitute(rest), False))
                continue
            if word == "SEANCE-MISSING-COPY":  # left by seance.copybook: only an error where the compiler reads it
                if cond.active:
                    from .copybook import CopyError

                    at, _, name = rest.partition(" ")
                    raise CopyError(f"line {at}: copybook {name} was not found. Add it with the program "
                                    f"(a file named {name.split()[0]}.cpy).")
                continue
            dm = cond.track(word, rest)
            if word in _CONDITIONAL:
                notes.add("directives")
            if dm is not None and dm.group(1) and dm.group(3):
                v = _constant_value(dm.group(3), consts)
                if v is not None:
                    remember(dm.group(2).upper(), v)
            continue  # a directive is never code
        if not cond.active:
            continue  # the branch the compiler leaves out
        # named constants
        cm = _CONST_78.match(ln.text) or _CONST_01.match(ln.text)
        if cm:
            v = _constant_value(cm.group(2), consts)
            if v is not None:
                remember(cm.group(1).upper(), v)
                continue
        text = substitute(ln.text)
        if comma and not re.search(r"\bDECIMAL-POINT\b", text, re.I):
            text = _outside_quotes(text, _comma_piece)
        if currency and currency != "$":
            text = _outside_quotes(text, lambda piece: _PIC.sub(lambda m: m.group(1) + m.group(2).replace(currency, "$"), piece))
        out.append(ln if text == ln.text else make_line(ln.number, text, False))
    done = []
    if "directives" in notes:
        done.append("Compiler directives (>>IF, >>DEFINE) were applied as GnuCOBOL applies them; no names are set on the command line.")
    if "constants" in notes:
        done.append("Named constants (level 78, CONSTANT) were replaced by their values.")
    return out, done
