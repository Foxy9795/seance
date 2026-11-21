"""What the compiler does to the text before it reads the program, done the same way here so the data layout,
the translator and the analysis all see the program GnuCOBOL compiles.

* Compiler directives: >>DEFINE, >>IF / >>ELIF / >>ELSE / >>END-IF (with IS [NOT] DEFINED, comparisons, AND, OR,
  NOT), >>SET CONSTANT. Other directives (>>TURN, >>PAGE, >>LISTING, $SET ...) change nothing the program computes
  here and are dropped.
* REPLACE ==a== BY ==b== [LEADING|TRAILING], REPLACE ALSO, REPLACE [LAST] OFF.
* Named constants: level 78 items, 01 name CONSTANT AS value, >>DEFINE CONSTANT. Each use is replaced by its value.

Lines keep their numbers, so every message and every # Lnn tag still points at the original source.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

WORD = r"[A-Za-z0-9][A-Za-z0-9_-]*"
_EDGE_L, _EDGE_R = r"(?<![A-Za-z0-9_-])", r"(?![A-Za-z0-9_-])"
_TOKEN = re.compile(r"\s*(>=|<=|<>|[=<>()]|'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[+-]?\d+(?:\.\d+)?|" + WORD + r")", re.I)


class PrecompileError(ValueError):
    pass


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


# ---------------------------------------------------------------- REPLACE

def _pseudo(text: str) -> list[tuple[str, str, str]]:
    """The (mode, from, to) pairs of a REPLACE statement's operands. mode is '', 'LEADING' or 'TRAILING'."""
    pairs = []
    for m in re.finditer(r"(?:(LEADING|TRAILING)\s+)?==(.*?)==\s+BY\s+==(.*?)==", text, re.I | re.S):
        pairs.append(((m.group(1) or "").upper(), " ".join(m.group(2).split()), " ".join(m.group(3).split())))
    return pairs


def _replacer(mode: str, old: str, new: str):
    if not old:
        return None
    if mode == "LEADING":
        rx = re.compile(_EDGE_L + re.escape(old) + r"(?=[A-Za-z0-9_-])", re.I)
    elif mode == "TRAILING":
        rx = re.compile(r"(?<=[A-Za-z0-9_-])" + re.escape(old) + _EDGE_R, re.I)
    else:
        words = old.split()
        rx = re.compile(_EDGE_L + r"\s+".join(re.escape(w) for w in words) + _EDGE_R, re.I)
    return rx, new


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


# ---------------------------------------------------------------- the pass

def apply(lines: list, make_line, debugging: bool = False) -> tuple[list, list[str]]:
    """lines: Line objects (number, text, comment). make_line(number, text, comment) builds a new one.
    debugging: the program says WITH DEBUGGING MODE, so >>D lines are compiled.
    Returns the lines the compiler reads, and notes about what was done."""
    defs: dict[str, str | None] = {}
    stack: list[list[bool]] = []  # [this branch is taken, a branch of this >>IF was taken already]
    consts: dict[str, str] = {}
    const_rx: re.Pattern | None = None
    rules: list[list] = []  # the REPLACE rules in force, newest last
    pending: str | None = None  # a REPLACE statement that continues on the next line
    notes: set[str] = set()
    out = []
    comma = any(not ln.comment and re.search(r"\bDECIMAL-POINT\s+IS\s+COMMA\b", ln.text, re.I) for ln in lines)
    # CURRENCY SIGN IS "W": pictures get the standard $ back, and the runtime shows the program's own sign
    currency = currency_symbol(" ".join(ln.text for ln in lines if not ln.comment))

    def active() -> bool:
        return all(s[0] for s in stack)

    def substitute(text: str) -> str:
        if const_rx is not None:
            text = _outside_quotes(text, lambda s: const_rx.sub(lambda m: consts[m.group(0).upper()], s))
        for rx, new in (r for group in rules for r in group):
            text = _outside_quotes(text, lambda s, rx=rx, new=new: rx.sub(new, s))
        return text

    for ln in lines:
        if ln.comment:
            out.append(ln)
            continue
        stripped = ln.text.strip()
        up = stripped.upper()
        if up.startswith(">>") or up.startswith("$"):
            m = re.match(r"(?:>>|\$)\s*([A-Z-]+)\s*(.*)$", stripped, re.I)
            word, rest = (m.group(1).upper(), m.group(2)) if m else ("", "")
            if word == "D":  # a debugging line
                if debugging and active() and rest.strip():
                    text = substitute(rest)
                    out.append(make_line(ln.number, text, False))
                continue
            if word == "IF":
                cond = active() and evaluate(rest, defs)
                stack.append([cond, cond])
                notes.add("directives")
            elif word in ("ELIF", "ELSE-IF") and stack:
                parent = all(s[0] for s in stack[:-1])
                cond = parent and not stack[-1][1] and evaluate(rest, defs)
                stack[-1] = [cond, stack[-1][1] or cond]
            elif word == "ELSE" and stack:
                parent = all(s[0] for s in stack[:-1])
                stack[-1] = [parent and not stack[-1][1], True]
            elif word == "END-IF" and stack:
                stack.pop()
            elif word in ("DEFINE", "SET") and active():
                dm = re.match(r"(?:(CONSTANT)\s+)?(" + WORD + r")(?:\s+AS\s+(.+?))?(?:\s+OVERRIDE)?\s*$", rest, re.I)
                if dm:
                    name, value = dm.group(2).upper(), dm.group(3)
                    if value and value.strip().upper() == "OFF":
                        defs.pop(name, None)
                    elif value and value.strip().upper() == "PARAMETER":
                        pass  # comes from the compile command line, which Séance does not set: stays undefined
                    else:
                        defs[name] = value.strip() if value else None
                        if dm.group(1) and value:
                            v = _constant_value(value, consts)
                            if v is not None:
                                consts[name] = v
                                const_rx = re.compile(_EDGE_L + "(" + "|".join(re.escape(k) for k in sorted(consts, key=len, reverse=True)) + ")" + _EDGE_R, re.I)
                notes.add("directives")
            continue  # a directive is never code
        if not active():
            continue  # the branch the compiler leaves out
        # REPLACE statements, possibly over several lines: one ends at a period outside its ==pseudo-text==
        if pending is not None or re.match(r"REPLACE\b", up):
            stmt = (pending + " " if pending is not None else "") + stripped
            outside = re.sub(r"==.*?==", "", stmt, flags=re.S)
            if stmt.count("==") % 2 or not re.search(r"\.\s*$", outside):
                pending = stmt
                continue
            pending = None
            body = stmt[len("REPLACE"):].strip().rstrip(".").strip()
            if re.fullmatch(r"(?i)(LAST\s+)?OFF", body):
                if re.match(r"(?i)LAST", body) and rules:
                    rules.pop()
                else:
                    rules.clear()
            else:
                also = bool(re.match(r"(?i)ALSO\b", body))
                group = [r for r in (_replacer(*p) for p in _pseudo(body)) if r]
                if also:
                    rules.append(group)
                else:
                    rules[:] = [group]
            notes.add("replace")
            continue
        # named constants
        cm = _CONST_78.match(ln.text) or _CONST_01.match(ln.text)
        if cm:
            v = _constant_value(cm.group(2), consts)
            if v is not None:
                consts[cm.group(1).upper()] = v
                const_rx = re.compile(_EDGE_L + "(" + "|".join(re.escape(k) for k in sorted(consts, key=len, reverse=True)) + ")" + _EDGE_R, re.I)
                notes.add("constants")
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
    if "replace" in notes:
        done.append("REPLACE statements were applied to the program text.")
    if "constants" in notes:
        done.append("Named constants (level 78, CONSTANT) were replaced by their values.")
    return out, done
