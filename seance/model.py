"""Understand a legacy program well enough to run it: its files, record layouts, console use and source format."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .cobol_src import detect_fixed, normalize, sentences, source_fixes
from .layout import Item, LayoutError, leaves, parse_entries, walk

ROOT = Path(__file__).resolve().parent.parent
# GnuCOBOL's own copybooks (screenio.cpy and the like), which cobc finds after the program's folder
GNUCOBOL_COPY = ROOT / "tools" / "gnucobol" / "gnucobol-3.1.2-windows-mingw-x64" / "share" / "gnucobol" / "copy"


def copy_dirs(*folders: Path) -> list[Path]:
    """Where COPY looks, in cobc's order: the folders given (as -I), then GnuCOBOL's copy folder."""
    import os

    out = [Path(f) for f in folders]
    extra = os.environ.get("COB_COPY_DIR")
    for d in ([Path(extra)] if extra else []) + [GNUCOBOL_COPY]:
        if d.is_dir() and d not in out:
            out.append(d)
    return out


class ModelError(ValueError):
    """The program uses something Séance cannot run yet. The message says what, and what to try."""


@dataclass
class FileDef:
    name: str  # name in SELECT / FD / OPEN
    assign: str  # external name from ASSIGN TO (a DD name or a file name)
    literal: bool
    organization: str  # "line" (LINE SEQUENTIAL), "sequential" (fixed-length), "indexed", "relative" or "sort" (an SD)
    status: str | None = None  # FILE STATUS data item
    records: list[Item] = field(default_factory=list)
    modes: set = field(default_factory=set)  # input, output, io, extend
    access: str = "sequential"  # sequential, random or dynamic
    record_key: str | None = None  # indexed: the RECORD KEY data item
    alt_keys: list[tuple[str, bool]] = field(default_factory=list)  # indexed: (ALTERNATE RECORD KEY, WITH DUPLICATES)
    relative_key: str | None = None  # relative: the RELATIVE KEY data item
    optional: bool = False
    raw_assign: str = ""  # the name as written (UT-S-REPORT), which GnuCOBOL also looks up
    contains: tuple[int, int] | None = None  # RECORD CONTAINS / IS VARYING: (smallest, largest) record
    same_record: int = 0  # I-O-CONTROL SAME RECORD AREA: files with the same number share one record area

    @property
    def variable(self) -> bool:
        """Records of more than one length. GnuCOBOL then writes each record of a sequential file behind a
        4-byte header (2-byte big-endian length, 2 zero bytes); measured: RECORD CONTAINS 120 with a 58-byte
        record gives 00 3A 00 00 before each record."""
        if self.organization != "sequential" or not self.records:
            return False
        sizes = {r.size for r in self.records}
        if self.contains:
            sizes |= {self.contains[0], self.contains[1]}
        return len(sizes) > 1

    @property
    def keyed(self) -> bool:
        return self.organization in ("indexed", "relative")

    @property
    def size(self) -> int:
        return max((r.size for r in self.records), default=0)

    @property
    def record(self) -> Item | None:
        return self.records[0] if self.records else None

    @property
    def is_input(self) -> bool:
        return self.organization != "sort" and bool(self.modes & {"input", "io", "extend"})

    @property
    def is_output(self) -> bool:
        return self.organization != "sort" and bool(self.modes & {"output", "io", "extend"})


@dataclass
class ProgramModel:
    name: str
    path: Path
    fixed: bool
    program_id: str
    files: list[FileDef]
    fd_items: dict[str, list[tuple[int, str]]]
    ws_items: list[tuple[int, str]]
    proc_items: list[tuple[int, str]]
    ws_records: list[Item]
    accepts: list[str]  # data names ACCEPTed from the console, in source order
    notes: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)  # statements the runner can never execute (EXEC SQL, CICS ...)
    linkage_records: list[Item] = field(default_factory=list)
    source: Path | None = None  # what is compiled and translated: the program itself, or its precompiled copy
    sql_tables: dict = field(default_factory=dict)  # EXEC SQL: tables from DECLARE TABLE (or schema.sql)
    cics: bool = False  # EXEC CICS: runs as a transaction
    using: list[str] = field(default_factory=list)  # PROCEDURE DIVISION USING: linkage records in order
    initial: bool = False  # PROGRAM-ID ... IS INITIAL: fresh storage on every CALL
    decimal_comma: bool = False  # SPECIAL-NAMES. DECIMAL-POINT IS COMMA: numbers are written 1.234,50
    currency: str = "$"  # SPECIAL-NAMES. CURRENCY SIGN IS "W": what edited fields show for the currency symbol
    special: object = None  # SPECIAL-NAMES: switches, CLASS tests, SYMBOLIC CHARACTERS, devices (seance.special_names)
    compile_source: Path | None = None  # the whole file GnuCOBOL compiles, when the file holds several programs
    in_main: bool = False  # a program of that same file: compiled with the main program, not on its own
    subprograms: list["ProgramModel"] = field(default_factory=list)  # other programs in the folder, reached by CALL
    calls: list[str] = field(default_factory=list)  # program names CALLed with a literal
    copy_dirs: list[Path] = field(default_factory=list)  # where its COPY statements found their copybooks

    def _every(self) -> list["ProgramModel"]:
        return [self] + [m for sub in self.subprograms for m in sub._every()]

    def _external(self, pick) -> list[FileDef]:
        seen, out = set(), []
        for m in self._every():
            for f in m.files:
                if pick(f) and f.assign not in seen:
                    seen.add(f.assign)
                    out.append(f)
        return out

    @property
    def inputs(self) -> list[FileDef]:
        """Files the run reads, in this program and every program it calls."""
        return self._external(lambda f: f.is_input)

    @property
    def outputs(self) -> list[FileDef]:
        return self._external(lambda f: f.is_output)

    @property
    def all_files(self) -> list[FileDef]:
        return self._external(lambda f: f.organization != "sort")

    @property
    def all_accepts(self) -> list[str]:
        return [a for m in self._every() for a in m.accepts]

    @property
    def compile_flags(self) -> list[str]:
        return ["-fixed" if self.fixed else "-free"]

    def file(self, name: str) -> FileDef:
        return next(f for f in self.files if f.name == name)

    def describe_io(self) -> str:
        parts = [f"reads {f.assign}" for f in self.inputs] + [f"writes {f.assign}" for f in self.outputs]
        if self.all_accepts:
            parts.append("reads console input")
        if self.subprograms:
            parts.append("calls " + ", ".join(m.program_id for m in self.subprograms))
        return ", ".join(parts) or "no files"


def code_sentences(path: Path, fixed: bool, dirs: list[Path], text: str | None = None) -> list[tuple[int, str]]:
    """The sentences the compiler reads from a program file: COPY statements expanded (seance.copybook), compiler
    directives and REPLACE applied, comments dropped. A COPY that cobc rejects is a ModelError."""
    from .copybook import CopyError

    try:
        return sentences(normalize(path.read_text(encoding="utf-8", errors="replace") if text is None else text, fixed, dirs))
    except CopyError as exc:
        raise ModelError(str(exc)) from exc


def _same_record_areas(text: str) -> list[list[str]]:
    """The file lists of I-O-CONTROL's SAME RECORD AREA clauses, in order. SAME AREA and SAME SORT AREA share no
    record storage in GnuCOBOL 3.1.2 (measured), so they are left out."""
    out = []
    for m in re.finditer(r"\bSAME\s+(RECORD\s+|SORT\s+|SORT-MERGE\s+)?(?:AREA\s+)?(?:FOR\s+)?(.*?)(?=\bSAME\b|\bAPPLY\b|\bMULTIPLE\b|\bRERUN\b|$)",
                         text, re.I | re.S):
        if (m.group(1) or "").strip().upper() == "RECORD":
            out.append([w.upper() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", m.group(2))])
    return out


_SELECT = re.compile(r"^SELECT\s+(?:OPTIONAL\s+)?([A-Z0-9-]+)\s+ASSIGN\s+(?:TO\s+)?(.*)$", re.I | re.S)


def _select_canonical(text: str) -> str:
    """A SELECT entry with its clauses in the usual words and order: the clauses may come in any order, and most of
    their keywords are optional (RECORD IX-KEY, STATUS IS FS OF GRP, a bare SEQUENTIAL, RESERVE 2 AREAS)."""
    toks = re.findall(r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|[^\s]+", text.strip())
    up = [t.upper() for t in toks]
    if not up or up[0] != "SELECT":
        return text
    i = 1
    head = ["SELECT"]
    if i < len(up) and up[i] == "OPTIONAL":
        head.append("OPTIONAL")
        i += 1
    if i >= len(up):
        return text
    head.append(toks[i])
    i += 1
    assign = org = access = status = key = rel = ""
    alts: list[str] = []
    others: list[str] = []

    def name_at(j: int) -> tuple[str, int]:
        """A data name and its qualifiers (FS OF GROUP); the qualifiers are dropped."""
        nm = up[j] if j < len(up) else ""
        j += 1
        while j + 1 < len(up) and up[j] in ("OF", "IN"):
            j += 2
        return nm, j

    while i < len(up):
        w = up[i]
        if w == "ASSIGN":
            i += 1
            if i < len(up) and up[i] == "TO":
                i += 1
            while i < len(up) and up[i] in ("EXTERNAL", "DYNAMIC", "DISK", "PRINTER", "KEYBOARD", "DISPLAY", "USING"):
                i += 1
            assign = toks[i] if i < len(toks) else ""
            i += 1
        elif w in ("ORGANIZATION", "ORGANISATION"):
            i += 1
            if i < len(up) and up[i] == "IS":
                i += 1
        elif w in ("LINE", "RECORD") and i + 1 < len(up) and up[i + 1] == "SEQUENTIAL":
            org = f"{w} SEQUENTIAL"
            i += 2
        elif w in ("SEQUENTIAL", "INDEXED") or (w == "RELATIVE" and not (i + 1 < len(up) and up[i + 1] == "KEY")):
            org = w  # ORGANIZATION IS may be left out
            i += 1
        elif w == "ACCESS":
            i += 1
            while i < len(up) and up[i] in ("MODE", "IS"):
                i += 1
            access = up[i] if i < len(up) else ""
            i += 1
        elif w in ("FILE", "STATUS") and (w == "STATUS" or (i + 1 < len(up) and up[i + 1] == "STATUS")):
            i += 1 if w == "STATUS" else 2
            if i < len(up) and up[i] == "IS":
                i += 1
            status, i = name_at(i)
            if i < len(up) and up[i] not in _SELECT_WORDS and re.fullmatch(r"[A-Z0-9-]+", up[i]):
                i += 1  # a second status item (VSAM return codes)
        elif w == "ALTERNATE":
            i += 1
            while i < len(up) and up[i] in ("RECORD", "KEY", "IS"):
                i += 1
            nm, i = name_at(i)
            dup = ""
            if i < len(up) and up[i] in ("WITH", "DUPLICATES"):
                i += 2 if up[i] == "WITH" else 1
                dup = " WITH DUPLICATES"
            alts.append(f"ALTERNATE RECORD KEY IS {nm}{dup}")
        elif w == "RECORD" and not (i + 1 < len(up) and up[i + 1] == "DELIMITER"):
            i += 1
            while i < len(up) and up[i] in ("KEY", "IS"):
                i += 1
            key, i = name_at(i)
            if i < len(up) and up[i] in ("=", "SOURCE"):
                others.append("SPLIT KEY")
        elif w == "RELATIVE":
            i += 1
            while i < len(up) and up[i] in ("KEY", "IS"):
                i += 1
            rel, i = name_at(i)
        elif w == "RESERVE":
            i += 2
            if i < len(up) and up[i] in ("AREA", "AREAS"):
                i += 1
        else:
            others.append(toks[i])
            i += 1
    if not assign:
        return text
    parts = head + ["ASSIGN", "TO", assign]
    if org:
        parts += ["ORGANIZATION", "IS", org]
    if access:
        parts += ["ACCESS", "MODE", "IS", access]
    if key:
        parts += ["RECORD", "KEY", "IS", key]
    parts += alts
    if rel:
        parts += ["RELATIVE", "KEY", "IS", rel]
    if status:
        parts += ["FILE", "STATUS", "IS", status]
    return " ".join(parts + others)


_SELECT_WORDS = {"ASSIGN", "ORGANIZATION", "ORGANISATION", "ACCESS", "FILE", "STATUS", "RECORD", "ALTERNATE", "RELATIVE", "RESERVE",
                 "LINE", "SEQUENTIAL", "INDEXED", "PADDING", "LOCK", "SHARING", "COLLATING"}


def _parse_select(text: str, line_no: int) -> FileDef:
    m = _SELECT.match(_select_canonical(text).strip())
    if not m:
        raise ModelError(f"line {line_no}: cannot read this SELECT: {text.strip()[:70]!r}")
    name, rest = m.group(1).upper(), m.group(2).strip()
    rest = re.sub(r"^(?:EXTERNAL|DYNAMIC|DISK|PRINTER|KEYBOARD|DISPLAY)\s+", "", rest, flags=re.I)
    tok = re.match(r"\"([^\"]*)\"|'([^']*)'|([A-Z0-9_$#@-]+)", rest, re.I)
    if not tok:
        raise ModelError(f"line {line_no}: cannot find the file name in ASSIGN for {name}.")
    literal = tok.group(1) is not None or tok.group(2) is not None
    assign = next(g for g in tok.groups() if g is not None)
    raw = assign
    if not literal:
        assign = re.sub(r"^(?:UT-S-|UR-S-|DA-S-|UT-|DA-|S-)", "", assign, flags=re.I)  # old IBM device prefixes
    upper = re.sub(r"\s+", " ", rest.upper())
    om = re.search(r"ORGANI[SZ]ATION (?:IS )?(LINE SEQUENTIAL|RECORD SEQUENTIAL|SEQUENTIAL|INDEXED|RELATIVE)", upper)
    org = {"LINE SEQUENTIAL": "line", "INDEXED": "indexed", "RELATIVE": "relative"}.get(om.group(1) if om else "", "sequential")
    if not om and re.search(r"\bLINE SEQUENTIAL\b", upper):
        org = "line"
    if org == "sequential" and re.search(r"\bRECORD KEY\b", upper):
        org = "indexed"
    sm = re.search(r"\bFILE STATUS (?:IS )?([A-Z0-9-]+)", upper)
    f = FileDef(name, Path(assign).name if literal else assign, literal, org, sm.group(1) if sm else None)
    f.optional = bool(re.match(r"^SELECT\s+OPTIONAL\b", text.strip(), re.I))
    f.raw_assign = raw.upper() if not literal else ""
    am = re.search(r"\bACCESS (?:MODE )?(?:IS )?(SEQUENTIAL|RANDOM|DYNAMIC)", upper)
    f.access = am.group(1).lower() if am else "sequential"
    km = re.search(r"(?<!ALTERNATE )\bRECORD KEY (?:IS )?([A-Z0-9-]+)", upper)
    f.record_key = km.group(1) if km else None
    f.alt_keys = [(k, bool(d)) for k, d in re.findall(r"ALTERNATE (?:RECORD )?KEY (?:IS )?([A-Z0-9-]+)((?: WITH)? DUPLICATES)?", upper)]
    rm = re.search(r"\bRELATIVE KEY (?:IS )?([A-Z0-9-]+)", upper)
    f.relative_key = rm.group(1) if rm else None
    if org == "indexed" and not f.record_key:
        raise ModelError(f"line {line_no}: indexed file {name} has no RECORD KEY.")
    if org == "indexed" and re.search(r"\bSPLIT KEY|SOURCE IS\b", upper):
        raise ModelError(f"line {line_no}: split keys on {name} are not supported yet.")
    return f


_OPEN_MODE = {"INPUT": "input", "OUTPUT": "output", "I-O": "io", "EXTEND": "extend"}


def _sort_modes(proc_text: str, files: dict[str, FileDef]) -> None:
    words = re.findall(r"[A-Z0-9-]+", proc_text.upper())
    for i, w in enumerate(words):
        if w not in ("USING", "GIVING"):
            continue
        mode = "input" if w == "USING" else "output"
        for name in words[i + 1:]:
            if name not in files or files[name].organization == "sort":
                break
            files[name].modes.add(mode)


def _modes(proc_text: str, files: dict[str, FileDef]) -> None:
    for m in re.finditer(r"\bOPEN\s+(.*?)(?=\.\s|$|\b(?:MOVE|PERFORM|READ|WRITE|DISPLAY|IF|CLOSE|ACCEPT|INITIALIZE|COMPUTE|ADD|SET|GO|STOP|EVALUATE|CALL|STRING|OPEN)\b)", proc_text, re.I | re.S):
        mode = None
        for w in re.findall(r"[A-Z0-9-]+", m.group(1).upper()):
            if w in _OPEN_MODE:
                mode = _OPEN_MODE[w]
            elif w in files and mode:
                files[w].modes.add(mode)


SOURCE_EXTENSIONS = (".cbl", ".cob", ".cobol")


LIMITS = (
)


def limit_notes(items: list[tuple[int, str]]) -> list[str]:
    """Constructs the translator is known not to handle, found in the source sentences. Each is said once."""
    out = []
    for pattern, why in LIMITS:
        if any(re.search(pattern, s.strip(), re.I) for _, s in items):
            out.append(why)
    return out


def split_programs(path: Path, out_dir: Path) -> dict[str, Path] | None:
    """A file that holds several programs, one after another or nested, as one file per program: each copy keeps only
    its own program's lines and leaves the others empty, so every line number stays the same. {program-id: file},
    the first program first; None when the file holds one program."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fixed = detect_fixed(text)
    raw = text.splitlines()

    def body(line: str) -> str:
        line = line.expandtabs(8)
        if fixed:
            return "" if len(line) > 6 and line[6] in "*/" else line[7:72]
        return "" if line.strip().startswith("*>") else line

    starts = [i for i, l in enumerate(raw) if re.match(r"\s*(IDENTIFICATION|ID)\s+DIVISION\b", body(l), re.I)]
    if len(starts) <= 1:
        return None
    bounds = [0] + starts[1:] + [len(raw)]
    out: dict[str, Path] = {}
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        seg = [raw[i] if a <= i < b and not re.match(r"\s*END\s+PROGRAM\b", body(raw[i]), re.I) else "" for i in range(len(raw))]
        pm = re.search(r"PROGRAM-ID\.?\s+['\"]?([A-Za-z0-9_-]+)", "\n".join(body(l) for l in raw[a:b]), re.I)
        pid = (pm.group(1) if pm else f"part{k + 1}").lower()
        target = out_dir / (path.name if k == 0 else f"{pid}.cbl")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(seg) + "\n"
        if not target.exists() or target.read_text(encoding="utf-8") != content:  # keep the date of an unchanged copy
            target.write_text(content, encoding="utf-8")
        out.setdefault(pid, target)
    return out


def load_model(program: str, root: Path = ROOT) -> ProgramModel:
    """The program in legacy/<program>/<program>.cbl, plus any other programs in that folder it CALLs."""
    path = root / "legacy" / program / f"{program}.cbl"
    src_dir = path.parent
    folders = [src_dir]  # where COPY looks, in the order the recorder passes them to cobc as -I
    sql = any(q.is_file() and re.search(r"\bEXEC\s+SQL\b", q.read_text(encoding="utf-8", errors="replace"), re.I) for q in src_dir.iterdir())
    pre = None
    if sql:  # precompile the folder; everything is then read from the plain-COBOL copy
        from .sqlpre import SqlError, precompile_folder

        try:
            pre = precompile_folder(src_dir, program, root / "build" / program / "sqlsrc")
        except SqlError as exc:
            raise ModelError(f"embedded SQL: {exc}") from exc
        src_dir = root / "build" / program / "sqlsrc"
        folders.insert(0, src_dir)
    cics = any(q.is_file() and re.search(r"\bEXEC\s+CICS\b", q.read_text(encoding="utf-8", errors="replace"), re.I) for q in src_dir.iterdir())
    cics_notes: list[str] = []
    if cics:  # CICS commands become CALLs of the CICS bridge (after SQL, if the program has both)
        from .cicspre import CicsError, precompile_folder as cics_precompile

        try:
            cics_notes = cics_precompile(src_dir, program, root / "build" / program / "cicssrc")
        except CicsError as exc:
            raise ModelError(f"CICS: {exc}") from exc
        src_dir = root / "build" / program / "cicssrc"
        folders.insert(0, src_dir)
    dirs = copy_dirs(*folders)
    split = split_programs(src_dir / path.name, root / "build" / program / "split")
    model = load_file(split[next(iter(split))] if split else src_dir / path.name, program, shown=path, dirs=dirs)
    if split:
        model.compile_source = src_dir / path.name
        model.notes.append(f"This file holds {len(split)} programs. Each is translated and compiled as a program of its own, so data "
                           "declared GLOBAL in one is not seen by the others.")
    if cics:
        model.notes.append("CICS: commands precompiled to CALLs of Séance's CICS bridge; files, temporary storage, the terminal "
                           "and the COMMAREA are kept in SQLite, and the transaction runs pseudo-conversationally.")
        model.notes += cics_notes
        model.files.append(FileDef("CICSDB", "CICSDB", False, "cicsdb", modes={"io"}))
        model.cics = True
    if pre is not None:
        model.sql_tables = pre.tables
        model.notes.append(f"Embedded SQL: {pre.statements} statement(s) precompiled to CALLs of Séance's SQL bridge, run on SQLite "
                           f"with tables {', '.join(pre.tables) or '(none declared)'}.")
        model.files.append(FileDef("SQLDB", "SQLDB", False, "sqldb", modes={"io"}))
    others = [q for q in sorted(src_dir.iterdir()) if q.is_file() and q.suffix.lower() in SOURCE_EXTENSIONS and q.name != path.name]
    subs: dict[str, ProgramModel] = {}
    for q in others:
        text = q.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"PROCEDURE\s+DIVISION", text, re.I):
            continue  # a copybook saved with a program extension
        try:
            sub = load_file(q, q.stem.lower(), shown=path.parent / q.name, dirs=dirs)
        except ModelError as exc:
            raise ModelError(f"{q.name}: {exc}") from exc
        subs[sub.program_id] = sub
    for pid, q in list(split.items())[1:] if split else []:
        try:
            sub = load_file(q, pid, shown=path.parent / q.name, dirs=dirs)
        except ModelError as exc:
            raise ModelError(f"program {pid.upper()} in {path.name}: {exc}") from exc
        sub.in_main = True
        subs[sub.program_id] = sub
    # keep only the programs reachable through CALL, in call order
    seen: set[str] = set()

    def reach(m: ProgramModel) -> list[ProgramModel]:
        out = []
        for name in m.calls:
            if name in subs and name not in seen:
                seen.add(name)
                out.append(subs[name])
                subs[name].subprograms = reach(subs[name])
        return out

    model.subprograms = reach(model)
    missing = sorted({c for m in model._every() for c in m.calls} - set(subs) - {model.program_id})
    for name in missing:
        model.notes.append(f"It CALLs {name}, which is not in this program's folder. Add {name}'s source to run that CALL.")
    return model


def load_file(path: Path, program: str, shown: Path | None = None, dirs: list[Path] | None = None) -> ProgramModel:
    """shown: the file people see (the original when path is a precompiled copy). dirs: where COPY looks."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fixed = detect_fixed(text)
    dirs = dirs if dirs is not None else copy_dirs(path.parent)
    try:
        items = code_sentences(path, fixed, dirs, text)
    except OSError as exc:
        raise ModelError(str(exc)) from exc
    files: dict[str, FileDef] = {}
    fd_items: dict[str, list[tuple[int, str]]] = {}
    fd_contains: dict[str, tuple[int, int]] = {}
    sd_names: set[str] = set()
    io_control: list[str] = []
    ws: list[tuple[int, str]] = []
    link: list[tuple[int, str]] = []
    proc: list[tuple[int, str]] = []
    section, current_fd = "", ""
    unsupported: list[str] = []
    using: list[str] = []
    for line_no, s in items:
        up = s.upper().strip()
        if re.match(r"^END\s+PROGRAM\b", up):
            break  # nested or following programs in the same file are not read
        if re.match(r"^(FILE|WORKING-STORAGE|LOCAL-STORAGE|LINKAGE|REPORT|SCREEN|COMMUNICATION)\s+SECTION$", up):
            section, current_fd = up.split()[0], ""
            if section in ("REPORT", "SCREEN", "COMMUNICATION"):
                unsupported.append(f"{section} SECTION")
            continue
        if re.match(r"^PROCEDURE\s+DIVISION", up):
            if re.search(r"\bRETURNING\b", up):
                unsupported.append("PROCEDURE DIVISION RETURNING (GnuCOBOL 3.1.2 does not implement it, so there is no original to compare with)")
            um = re.search(r"\bUSING\s+(.*?)(?:\bRETURNING\b.*)?$", up)
            if um:
                using = [w for w in re.findall(r"[A-Z0-9-]+", um.group(1)) if w not in ("BY", "REFERENCE", "VALUE", "CONTENT", "OPTIONAL")]
            section = "PROCEDURE"
            continue
        if up == "FILE-CONTROL":
            section = "FILE-CONTROL"
            continue
        if re.match(r"^(IDENTIFICATION|ID|ENVIRONMENT|DATA)\s+DIVISION$|^(INPUT-OUTPUT|CONFIGURATION)\s+SECTION$|^I-O-CONTROL$", up):
            if up == "I-O-CONTROL":
                section = "I-O-CONTROL"
            continue
        if section == "FILE-CONTROL" and up.startswith("SELECT"):
            f = _parse_select(s, line_no)
            files[f.name] = f
        elif section == "I-O-CONTROL":
            io_control.append(up)
        elif section == "FILE" and re.match(r"^(FD|SD)\s", up):
            current_fd = re.match(r"^(?:FD|SD)\s+([A-Z0-9-]+)", up).group(1)
            if up.startswith("SD"):
                sd_names.add(current_fd)
            fd_items.setdefault(current_fd, [])
            vm = re.search(r"\bRECORD\s+(?:IS\s+)?VARYING\s+(?:IN\s+SIZE\s+)?(?:FROM\s+)?(\d+)?\s*(?:TO\s+(\d+))?", up)
            cm = re.search(r"\bRECORD\s+(?:CONTAINS\s+)?(\d+)(?:\s+TO\s+(\d+))?\s+CHARACTERS", up)
            if vm and (vm.group(1) or vm.group(2)):
                fd_contains[current_fd] = (int(vm.group(1) or 1), int(vm.group(2) or vm.group(1)))
            elif cm:
                fd_contains[current_fd] = (int(cm.group(1)), int(cm.group(2) or cm.group(1)))
        elif section == "FILE" and current_fd and re.match(r"^\d{1,2}\s", up):
            fd_items[current_fd].append((line_no, s))
        elif section in ("WORKING-STORAGE", "LOCAL-STORAGE") and re.match(r"^\d{1,2}\s", up):
            ws.append((line_no, s))
        elif section == "LINKAGE" and re.match(r"^\d{1,2}\s", up):
            link.append((line_no, s))
        elif section == "PROCEDURE":
            proc.append((line_no, s))
    for name in sd_names:
        if name in files:
            files[name].organization = "sort"
    for group, names in enumerate(_same_record_areas(" ".join(io_control)), start=1):
        for name in names:
            if name in files:
                files[name].same_record = group  # a later SAME RECORD AREA takes a file away from an earlier one
    for name, c in fd_contains.items():
        if name in files:
            files[name].contains = c
    try:
        for name, f in files.items():
            if name in fd_items:
                f.records = parse_entries(fd_items[name])
            if not f.records:
                raise ModelError(f"No FD record description found for {name}.")
        ws_records = parse_entries(ws)
        linkage = parse_entries(link)
    except LayoutError as exc:
        raise ModelError(str(exc)) from exc

    proc_text = " ".join(s for _, s in proc)
    _modes(proc_text, files)
    _sort_modes(proc_text, files)
    for f in files.values():
        if not f.modes:
            f.modes.add("unused")
    for word, why in (("EXEC SQL", "embedded SQL (EXEC SQL) needs a database"), ("EXEC CICS", "CICS commands need a CICS region"),
                      ("EXEC DLI", "IMS DL/I calls need an IMS region")):
        if re.search(rf"(?<![A-Z0-9-]){word}", proc_text.upper()):
            unsupported.append(why)

    accepts = []
    for m in re.finditer(r"\bACCEPT\s+([A-Z0-9-]+)(?:\s*\([^)]*\))?(?!\s+FROM)", proc_text, re.I):
        accepts.append(m.group(1).upper())
    calls = []
    for m in re.finditer(r"\bCALL\s+['\"]([A-Za-z0-9_-]+)['\"]|\bEXEC\s+CICS\s+(?:LINK|XCTL)\s+PROGRAM\s*\(\s*['\"]([A-Za-z0-9_-]+)", proc_text, re.I):
        name = (m.group(1) or m.group(2)).upper()
        if name not in calls:
            calls.append(name)
    for m in []:
        if m.group(1).upper() not in calls:
            calls.append(m.group(1).upper())
    pid, initial = program.upper(), False
    for k, (_, s) in enumerate(items):
        if re.match(r"^PROGRAM-ID\b", s.strip(), re.I):
            # "PROGRAM-ID. NAME." splits into two sentences; "PROGRAM-ID NAME" stays one
            rest = s.split(None, 1)[1] if len(s.split()) > 1 else (items[k + 1][1] if k + 1 < len(items) else "")
            if rest.strip():
                pid = re.sub(r"[.\s].*$", "", rest.strip())
                initial = bool(re.search(r"\bINITIAL\b", rest, re.I))
            break
    model = ProgramModel(program, shown or path, fixed, pid.strip("'\"").upper(), list(files.values()), fd_items, ws, proc, ws_records, accepts,
                         [], sorted(set(unsupported)), linkage_records=linkage, using=using, initial=initial,
                         calls=[c for c in calls if c not in ("SQLBRIDGE", "DSNTIAR", "CICSBRIDGE")], source=path, copy_dirs=dirs)
    if not proc:
        raise ModelError("No PROCEDURE DIVISION statements were found.")
    missing = [u for u in using if u not in {r.name for r in linkage}]
    if missing:
        raise ModelError(f"PROCEDURE DIVISION USING names {', '.join(missing)}, which is not a 01 or 77 item in the LINKAGE SECTION.")
    model.notes += source_fixes(text, fixed)[1]
    model.notes += limit_notes(items)
    model.decimal_comma = any(re.search(r"\bDECIMAL-POINT\s+IS\s+COMMA\b", s, re.I) for _, s in items)
    from .precompile import currency_symbol, currency_text
    from .special_names import from_sentences

    model.special = from_sentences(items)

    sign = currency_text(" ".join(s for _, s in items))
    if sign and sign != "$":
        if len(sign) != 1 or currency_symbol(" ".join(s for _, s in items)) is None:
            raise ModelError(f"CURRENCY SIGN IS \"{sign}\": a currency sign of more than one character is not supported yet.")
        model.currency = sign
    for f in model.files:
        if f.organization == "line" and any(lf.item.usage != "display" for r in f.records for lf in leaves(r)):
            model.notes.append(f"{f.name} is a text (LINE SEQUENTIAL) file but its record has binary or packed fields.")
        for key in [f.record_key, f.relative_key, *[k for k, _ in f.alt_keys]]:
            if key and f.organization == "indexed" and key != f.relative_key and not any(it.name == key for r in f.records for it in walk(r)):
                raise ModelError(f"The key {key} of indexed file {f.name} must be a field of its record.")
    return model
