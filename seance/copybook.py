"""COPY and REPLACE, done the way GnuCOBOL 3.1.2's preprocessor does them (cobc/pplex.l and cobc/ppparse.y).

    COPY text-name [{OF | IN} library-name] [SUPPRESS [PRINTING]] [REPLACING operand BY operand ...] .
    REPLACE [ALSO] operand BY operand ... .        REPLACE [LAST] OFF .

A COPY statement, from COPY to its period, gives way to the copybook's text, which starts on a line of its own;
what follows the period goes on after it, so a COPY may sit in the middle of an entry or a statement. Copybooks may
COPY others. Every copied line takes the number of the line with the outermost COPY, so what came from a copybook
points at the COPY that brought it in. (cobc also reads INCLUDE as COPY; Séance does not, so that EXEC SQL INCLUDE
stays for the SQL precompiler.)

REPLACING and REPLACE work on text words the way cobc compares them, which is not always the standard's way:
- spaces, a comma or semicolon before a space, line ends and comment lines are skipped when comparing;
- words and literals compare without regard to case ('pig' matches 'PIG');
- the replacement goes out as written and is not compared again;
- when an operand fails part way, every word held for it goes out unchanged (the standard steps back one word);
- LEADING ==x== and TRAILING ==x== change the start or the end of one word.
A COPY's operands apply to its copybook and to the copybooks that one copies, inner operands first; the REPLACE
operands in force come after them, and apply to the program's own text too. REPLACE ALSO adds operands in front
of those in force, REPLACE LAST OFF takes them away again, REPLACE OFF ends them all.

A copybook is looked up as cobc looks for it: library/name first when a library is named, then the name alone,
in each include directory, with no extension, then .CPY .CBL .COB .cpy .cbl .cob (a name with a period is only
tried as written). Statements in a branch >>IF leaves out are not done.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from pathlib import Path

from .cobol_src import Line, detect_fixed, read_lines, read_source
from .precompile import Conditions, directive

EXTENSIONS = ("", ".CPY", ".CBL", ".COB", ".cpy", ".cbl", ".cob")
MISSING = "SEANCE-MISSING-COPY"  # left as a directive where a copybook was not found; an error where it is compiled
MAX_DEPTH = 50

_WCH = "_0-9A-Za-z\u0080-\U0010ffff-"
_FOLD = str.maketrans(string.ascii_lowercase, string.ascii_uppercase)  # strcasecmp folds ASCII letters only
_KEYWORDS = {"BY", "IN", "OF", "OFF", "SUPPRESS", "PRINTING", "REPLACING", "LEADING", "TRAILING", "ALSO", "LAST"}

_WORD = re.compile("[" + _WCH + "]+")
_NUM = re.compile(r"[+-]?[0-9,.]*[0-9]")
_LIT = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")
_NAME = re.compile("[" + _WCH + "]+(?:\\.[" + _WCH + "]+)+")  # a copybook name with periods, written without quotes
_EXEC = re.compile(r"(?<![A-Z0-9_-])(END-EXEC|EXEC)(?![A-Z0-9_-])")


class CopyError(ValueError):
    """A COPY or REPLACE statement cobc rejects: a missing copybook, a statement written wrongly, a copybook that
    copies itself."""


@dataclass(frozen=True)
class Rule:
    """One operand pair of REPLACING or REPLACE, as text words. A word that starts with a space is a separator."""

    old: tuple[str, ...]
    new: tuple[str, ...]
    mode: str = ""  # "", "LEADING" or "TRAILING"


@dataclass(frozen=True)
class Statement:
    kind: str  # "COPY" or "REPLACE"
    name: str = ""  # COPY: the copybook
    library: str | None = None
    rules: tuple[Rule, ...] = ()
    action: str = ""  # REPLACE: "" (these operands only), "ALSO", "OFF" or "LAST OFF"


def _fold(s: str) -> str:
    return s.translate(_FOLD)


def _longest(text: str, i: int, *patterns: re.Pattern) -> str:
    best = text[i]
    for rx in patterns:
        m = rx.match(text, i)
        if m and len(m.group()) > len(best):
            best = m.group()
    return best


# ---------------------------------------------------------------- text words

def text_words(text: str) -> list[str]:
    """One line as cobc's scanner passes it on: words, numbers, literals and single characters, and a run of
    separators as spaces of the same width (inside parentheses a comma before a space stays a comma)."""
    out: list[str] = []
    i, n, depth = 0, len(text), 0
    while i < n:
        ch = text[i]
        if ch in ",;" and i + 1 == n:
            break  # a separator at the end of the line goes with the line end
        if ch in " \t" or (ch in ",;" and text[i + 1] in " \t"):
            j = i + 1
            while j < n and text[j] in " \t":
                j += 1
            out.append("," + " " * (j - i - 1) if ch == "," and depth else " " * (j - i))
            i = j
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        word = ch if ch in "()" else _longest(text, i, _WORD, _NUM, _LIT)
        out.append(word)
        i += len(word)
    return out


class _Replacer:
    """cobc's ppecho: words wait in a queue while an operand may still match them. Words carry their line number."""

    def __init__(self) -> None:
        self.queue: list[tuple[str, int]] = []
        self.out: list[tuple[str, int]] = []

    def feed(self, word: str, no: int, rules: tuple[Rule, ...]) -> None:
        if not self.queue and word[0] in " \n":
            self.out.append((word, no))
            return
        if not rules:
            self.flush()
            self.out.append((word, no))
            return
        self.queue.append((word, no))
        start = 0
        for r in rules:
            q, size, keep, held, first = start, 0, 0, "", None
            matched = True
            for old in r.old:
                if old[0] in " \n":
                    continue
                while q < len(self.queue) and self.queue[q][0][0] in " \n":
                    q += 1
                if q == len(self.queue):
                    del self.queue[:start]
                    return  # it may still match: wait for the next word
                cur = self.queue[q][0]
                if r.mode == "LEADING":
                    size = len(old)
                    matched = _fold(cur[:size]) == _fold(old)
                elif r.mode == "TRAILING":
                    size, keep = len(old), len(cur) - len(old)
                    matched = keep >= 0 and _fold(cur[keep:]) == _fold(old)
                else:
                    matched = _fold(cur) == _fold(old)
                if not matched:
                    break
                if first is None:
                    first = self.queue[q][1]
                held = cur
                q += 1
            if matched:
                at = no if first is None else first
                if r.mode == "TRAILING" and held[:keep]:
                    self.out.append((held[:keep], at))
                self.out.extend((w, at) for w in r.new)
                if r.mode == "LEADING" and held[size:]:
                    self.out.append((held[size:], at))
                start = q
        self.out.extend(self.queue[start:])
        self.queue.clear()

    def flush(self) -> None:
        self.out.extend(self.queue)
        self.queue.clear()


# ---------------------------------------------------------------- statements

def find_statement(text: str, copies: bool = True) -> tuple[str, int, int] | None:
    """The first COPY or REPLACE statement in a line of code, outside literals: (kind, start of the word, end of the
    word). copies: look for COPY too."""
    up = _fold(text)
    if "REPLACE" not in up and not (copies and "COPY" in up):
        return None
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t,;()":
            i += 1
            continue
        word = _longest(text, i, _WORD, _NUM, _LIT)
        end = i + len(word)
        w = _fold(word)
        if (w == "REPLACE" or (copies and w == "COPY")) and (end == n or text[end] in " \t,;"):
            return w, i, end
        i = end
    return None


@dataclass
class _Tok:
    kind: str  # "word", "name" (with periods), "kw", "dot", "pseudo", "(", ")"
    text: str
    end: int  # offset just past the token
    words: tuple[str, ...] = ()  # pseudo-text: its text words


def _pseudo(s: str, i: int) -> tuple[tuple[str, ...], int]:
    """The text words of ==pseudo-text== starting just after its opening ==, and the offset after the closing ==."""
    words: list[str] = []
    n = len(s)
    while i < n:
        if s.startswith("==", i):
            return tuple(words), i + 2
        ch = s[i]
        if ch == "\n" or (ch in ",;" and i + 1 < n and s[i + 1] == "\n"):
            i += 1 if ch == "\n" else 2  # a line end inside pseudo-text is no word
            continue
        if ch in " \t" or (ch in ",;" and i + 1 < n and s[i + 1] in " \t"):
            j = i + 1
            while j < n and s[j] in " \t":
                j += 1
            words.append(" ")
            i = j
            continue
        word = _longest(s, i, _WORD, _NUM, _LIT)
        words.append(word)
        i += len(word)
    raise CopyError("the ==pseudo-text== is not closed with ==")


def _statement_tokens(s: str) -> list[_Tok]:
    """The words of a COPY or REPLACE statement after its first word, up to and including its period."""
    toks: list[_Tok] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch in " \t\n" or (ch in ",;" and (i + 1 == n or s[i + 1] in " \t\n")):
            i += 1
            continue
        if s.startswith("==", i):
            words, i = _pseudo(s, i + 2)
            toks.append(_Tok("pseudo", "", i, words))
            continue
        if ch in "()":
            i += 1
            toks.append(_Tok(ch, ch, i))
            continue
        word = _longest(s, i, _NAME, _WORD, _NUM, _LIT)
        if word == ".":
            toks.append(_Tok("dot", ".", i + 1))
            return toks
        m = _NAME.match(s, i)
        kind = "name" if m and m.group() == word else ("kw" if _fold(word) in _KEYWORDS else "word")
        i += len(word)
        toks.append(_Tok(kind, word, i))
    return toks


def _complete(after: str) -> bool:
    """Whether the text after COPY or REPLACE holds the whole statement, period included."""
    try:
        toks = _statement_tokens(after)
    except CopyError:
        return False  # pseudo-text still open
    return bool(toks) and toks[-1].kind == "dot"


def _unquote(word: str) -> str:
    return word[1:-1] if len(word) >= 2 and word[0] in "\"'" and word[-1] == word[0] else word


class _Reader:
    def __init__(self, toks: list[_Tok]):
        self.toks, self.k = toks, 0

    def peek(self, kind: str | None = None, text: str | None = None, at: int = 0) -> bool:
        if self.k + at >= len(self.toks):
            return False
        t = self.toks[self.k + at]
        return (kind is None or t.kind == kind) and (text is None or _fold(t.text) == text)

    def take(self) -> _Tok:
        self.k += 1
        return self.toks[self.k - 1]

    def operand(self, partial: bool) -> tuple[str, ...]:
        """==pseudo-text==, or an identifier: a word or literal with IN/OF qualifiers and (subscripts)."""
        if self.peek("pseudo"):
            words = self.take().words
            if partial:
                words = tuple(w for w in words if w != " ")
                if len(words) > 1:
                    raise CopyError("LEADING and TRAILING take ==pseudo-text== of one word")
            return words
        if partial or not (self.peek("word") or self.peek("name")):
            raise CopyError("REPLACING needs ==pseudo-text==, a word or a literal on each side of BY")
        words = [self.take().text]
        while True:
            if (self.peek("kw", "IN") or self.peek("kw", "OF")) and (self.peek("word", at=1) or self.peek("name", at=1)):
                words += [" ", _fold(self.take().text), " ", self.take().text]
            elif self.peek("("):
                self.take()
                subs: list[str] = []
                while self.peek("word") or self.peek("name"):
                    subs += ([" "] if subs else []) + [self.take().text]
                if not self.peek(")"):
                    raise CopyError("a subscript in REPLACING is not closed with )")
                self.take()
                words += [" ", "("] + subs + [")"]
            else:
                return tuple(words)

    def replacing(self) -> tuple[Rule, ...]:
        rules: list[Rule] = []
        while not self.peek("dot"):
            mode = ""
            if self.peek("kw", "LEADING") or self.peek("kw", "TRAILING"):
                mode = _fold(self.take().text)
            old = self.operand(bool(mode))
            if not [w for w in old if w != " "]:
                raise CopyError("the text to replace is empty")
            if not self.peek("kw", "BY"):
                raise CopyError("the operands are written old BY new")
            self.take()
            rules.append(Rule(old, self.operand(bool(mode)), mode))
        if not rules:
            raise CopyError("REPLACING names nothing to replace")
        return tuple(rules)


def parse(kind: str, after: str) -> tuple[Statement, int]:
    """The COPY or REPLACE statement whose text after its first word is `after` (lines joined with \\n). Returns
    it and the offset just past its period."""
    toks = _statement_tokens(after)
    if not toks or toks[-1].kind != "dot":
        raise CopyError(f"the {kind} statement has no period at its end")
    r = _Reader(toks)
    if kind == "REPLACE":
        if r.peek("kw", "OFF"):
            r.take()
            stmt = Statement("REPLACE", action="OFF")
        elif r.peek("kw", "LAST") and r.peek("kw", "OFF", at=1):
            r.take()
            r.take()
            stmt = Statement("REPLACE", action="LAST OFF")
        else:
            also = r.peek("kw", "ALSO")
            if also:
                r.take()
            stmt = Statement("REPLACE", rules=r.replacing(), action="ALSO" if also else "")
    else:
        if not (r.peek("word") or r.peek("name")):
            raise CopyError("COPY must be followed by the name of a copybook")
        name = _unquote(r.take().text)
        library = None
        if r.peek("kw", "OF") or r.peek("kw", "IN"):
            r.take()
            if not (r.peek("word") or r.peek("name")):  # a library name may have periods in it
                raise CopyError(f"COPY {name} OF needs a library name")
            library = _unquote(r.take().text)
        if r.peek("kw", "SUPPRESS"):
            r.take()
            if r.peek("kw", "PRINTING"):
                r.take()
        rules: tuple[Rule, ...] = ()
        if r.peek("kw", "REPLACING"):
            r.take()
            rules = r.replacing()
        stmt = Statement("COPY", name, library, rules)
    if not r.peek("dot"):
        raise CopyError(f"unexpected {r.toks[r.k].text or 'text'} in the {kind} statement")
    return stmt, r.take().end


def find(name: str, library: str | None, dirs: list[Path]) -> Path | None:
    """The copybook cobc opens for COPY name [OF library], or None."""
    exts = ("",) if "." in name else EXTENSIONS

    def try_open(base: Path) -> Path | None:
        for ext in exts:
            p = base.with_name(base.name + ext)
            if p.is_file():
                return p
        folder = base.parent
        if folder.is_dir():  # a file system that tells upper from lower case (cobc's Windows build does not)
            wanted = {_fold(base.name + ext) for ext in exts}
            for p in sorted(folder.iterdir()):
                if p.is_file() and _fold(p.name) in wanted:
                    return p
        return None

    def search(rel: str) -> Path | None:
        if Path(rel).is_absolute():
            return try_open(Path(rel))
        for d in dirs:
            found = try_open(Path(d) / rel)
            if found:
                return found
        return None

    return (search(f"{library}/{name}") if library else None) or search(name)


# ---------------------------------------------------------------- the pass

def expand(lines: list[Line], dirs: list[Path] | None, debugging: bool) -> list[Line]:
    """The program's lines after COPY and REPLACE. dirs: where COPY looks; None leaves COPY statements as written."""
    p = _Pass(dirs, debugging)
    p.run(list(lines), (), (), None)
    p.drain()
    return p.out


class _Pass:
    def __init__(self, dirs: list[Path] | None, debugging: bool):
        self.dirs = dirs
        self.debugging = debugging
        self.base: tuple[Rule, ...] = ()  # REPLACE operands in force
        self.saved: list[tuple[Rule, ...]] = []  # what REPLACE LAST OFF goes back to
        self.cond = Conditions()
        self.rep = _Replacer()
        self.out: list[Line] = []
        self.in_exec = False  # inside EXEC ... END-EXEC

    def lines(self) -> None:
        """The replacer's output so far, made into lines (each takes the number of its first word)."""
        text, no = "", None
        for word, n in self.rep.out:
            if word == "\n":
                if text.strip():
                    self.out.append(Line(no if no is not None else n, text.rstrip()))
                text, no = "", None
                continue
            if no is None and word.strip():
                no = n
            text += word
        if text.strip():
            self.out.append(Line(no, text.rstrip()))
        self.rep.out.clear()

    def drain(self) -> None:
        self.rep.flush()
        self.lines()

    def put(self, no: int, text: str, rules: tuple[Rule, ...]) -> None:
        rules = rules + self.base
        if not rules and not self.rep.queue:
            self.lines()
            self.out.append(Line(no, text))
            return
        for w in text_words(text):
            self.rep.feed(w, no, rules)
        self.rep.feed("\n", no, rules)

    def replace(self, stmt: Statement) -> None:
        if stmt.action == "OFF":
            self.base, self.saved = (), []
        elif stmt.action == "LAST OFF":
            self.base = self.saved.pop() if self.saved else ()
        elif stmt.action == "ALSO" and self.base:
            self.saved.append(self.base)
            self.base = stmt.rules + self.base
        else:
            self.base, self.saved = stmt.rules, []

    def run(self, work: list[Line], rules: tuple[Rule, ...], chain: tuple[Path, ...], number: int | None) -> None:
        """work: the program's lines (number None) or a copybook's (number: the line of the outermost COPY).
        rules: the REPLACING operands of the COPY statements that brought this text in, innermost first."""
        i = 0
        while i < len(work):
            ln = work[i]
            no = ln.number if number is None else number
            if ln.comment:
                if number is None:  # a copybook's comments are left out
                    self.lines()  # words held for a match stay held: a comment line counts as a space
                    self.out.append(ln)
                i += 1
                continue
            d = directive(ln.text)
            if d is not None:
                self.drain()
                self.cond.track(*d)
                self.out.append(Line(no, ln.text))  # the precompile pass reads it again
                i += 1
                continue
            if not self.cond.active:
                i += 1
                continue
            if self.in_exec or _EXEC.search(_fold(_LIT.sub(" ", ln.text))):  # the word EXEC, not EXEC-COUNT
                # inside EXEC SQL ... END-EXEC nothing is COPY or REPLACE: EXEC SQL INCLUDE and the SQL REPLACE
                # function are the SQL precompiler's
                marks = _EXEC.findall(_fold(_LIT.sub(" ", ln.text)))
                self.in_exec = (marks[-1] == "EXEC") if marks else self.in_exec
                self.put(no, ln.text, rules)
                i += 1
                continue
            hit = find_statement(ln.text, self.dirs is not None)
            if hit is None:
                self.put(no, ln.text, rules)
                i += 1
                continue
            kind, at, after = hit
            where = f"line {no}"
            # the statement may run onto the next lines (comment lines between are skipped) up to its period
            spans, starts, joined = [(i, after)], [0], ln.text[after:] + "\n"
            j = i + 1
            while not _complete(joined):
                while j < len(work) and work[j].comment:
                    j += 1
                if j == len(work):
                    raise CopyError(f"{where}: the {kind} statement has no period at its end.")
                spans.append((j, 0))
                starts.append(len(joined))
                joined += work[j].text + "\n"
                j += 1
            try:
                stmt, end = parse(kind, joined)
            except CopyError as exc:
                raise CopyError(f"{where}: {exc}.") from None
            k = max(x for x in range(len(starts)) if starts[x] < end)  # the line the period is on
            last, col = spans[k]
            rest = work[last].text[col + (end - starts[k]):]
            if ln.text[:at].strip():
                self.put(no, ln.text[:at].rstrip(), rules)
            self.drain()
            if kind == "REPLACE":
                self.replace(stmt)
            else:
                self.copy(stmt, rules, chain, no, where)
            if rest.strip():
                work[last] = Line(work[last].number, rest)
                i = last
            else:
                i = last + 1

    def copy(self, stmt: Statement, rules: tuple[Rule, ...], chain: tuple[Path, ...], no: int, where: str) -> None:
        path = find(stmt.name, stmt.library, self.dirs or [])
        if path is None:
            lib = f" in library {stmt.library}" if stmt.library else ""
            self.out.append(Line(no, f">>{MISSING} {no} {stmt.name}{lib}"))
            return
        resolved = path.resolve()
        if resolved in chain:
            raise CopyError(f"{where}: copybook {stmt.name} copies itself.")
        if len(chain) >= MAX_DEPTH:
            raise CopyError(f"{where}: COPY statements are nested more than {MAX_DEPTH} deep.")
        text = read_source(path)
        body = read_lines(text, detect_fixed(text), self.debugging, entries=False)
        self.run(body, stmt.rules + rules, chain + (resolved,), no)
        self.drain()
