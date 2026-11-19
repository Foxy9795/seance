"""Understand a legacy program well enough to run it: its files, record layouts, console use and source format."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .cobol_src import detect_fixed, normalize, sentences, source_fixes
from .layout import Item, LayoutError, leaves, parse_entries, walk

ROOT = Path(__file__).resolve().parent.parent
COPY_EXTENSIONS = (".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB", ".copy", ".COPY", "")


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
    using: list[str] = field(default_factory=list)  # PROCEDURE DIVISION USING: linkage records in order
    initial: bool = False  # PROGRAM-ID ... IS INITIAL: fresh storage on every CALL
    subprograms: list["ProgramModel"] = field(default_factory=list)  # other programs in the folder, reached by CALL
    calls: list[str] = field(default_factory=list)  # program names CALLed with a literal

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


def _inline_copies(items: list[tuple[int, str]], include_dir: Path, depth: int = 0) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line_no, text in items:
        m = re.match(r"^COPY\s+['\"]?([A-Z0-9_.-]+?)['\"]?(?:\s+(?:OF|IN)\s+\S+)?(\s+REPLACING\b(.*))?$", text.strip(), re.I)
        if not m:
            out.append((line_no, text))
            continue
        if depth > 8:
            raise ModelError(f"line {line_no}: COPY statements are nested too deeply.")
        name = m.group(1)
        found = next((include_dir / f"{name}{ext}" for ext in COPY_EXTENSIONS if (include_dir / f"{name}{ext}").is_file()), None)
        if not found:
            found = next((p for p in include_dir.iterdir() if p.is_file() and p.stem.upper() == name.upper()), None)
        if not found:
            raise ModelError(f"line {line_no}: copybook {name} was not found. Add it with the program (a file named {name}.cpy).")
        body = _inline_copies(sentences(normalize(found.read_text(encoding="utf-8", errors="replace"))), include_dir, depth + 1)
        if m.group(2):
            pairs = re.findall(r"==\s*(.*?)\s*==\s+BY\s+==\s*(.*?)\s*==|(\S+)\s+BY\s+(\S+)", m.group(3), re.I)
            reps = [((a or c), (b if a else d)) for a, b, c, d in pairs]
            fixed_body = []
            for n, t in body:
                for old, new in reps:
                    t = re.sub(rf"(?<![A-Z0-9-]){re.escape(old)}(?![A-Z0-9-])" if re.fullmatch(r"[A-Z0-9-]+", old, re.I) else re.escape(old), new, t, flags=re.I)
                fixed_body.append((n, t))
            body = fixed_body
        out.extend(body)
    return out


_SELECT = re.compile(r"^SELECT\s+(?:OPTIONAL\s+)?([A-Z0-9-]+)\s+ASSIGN\s+(?:TO\s+)?(.*)$", re.I | re.S)


def _parse_select(text: str, line_no: int) -> FileDef:
    m = _SELECT.match(text.strip())
    if not m:
        raise ModelError(f"line {line_no}: cannot read this SELECT: {text.strip()[:70]!r}")
    name, rest = m.group(1).upper(), m.group(2).strip()
    rest = re.sub(r"^(?:EXTERNAL|DYNAMIC|DISK|PRINTER|KEYBOARD|DISPLAY)\s+", "", rest, flags=re.I)
    tok = re.match(r"\"([^\"]*)\"|'([^']*)'|([A-Z0-9_$#@-]+)", rest, re.I)
    if not tok:
        raise ModelError(f"line {line_no}: cannot find the file name in ASSIGN for {name}.")
    literal = tok.group(1) is not None or tok.group(2) is not None
    assign = next(g for g in tok.groups() if g is not None)
    if not literal:
        assign = re.sub(r"^(?:UT-S-|UR-S-|S-)", "", assign, flags=re.I)  # old IBM device prefixes
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


def load_model(program: str, root: Path = ROOT) -> ProgramModel:
    """The program in legacy/<program>/<program>.cbl, plus any other programs in that folder it CALLs."""
    path = root / "legacy" / program / f"{program}.cbl"
    model = load_file(path, program)
    others = [q for q in sorted(path.parent.iterdir()) if q.is_file() and q.suffix.lower() in SOURCE_EXTENSIONS and q.name != path.name]
    subs: dict[str, ProgramModel] = {}
    for q in others:
        text = q.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"PROCEDURE\s+DIVISION", text, re.I):
            continue  # a copybook saved with a program extension
        try:
            sub = load_file(q, q.stem.lower())
        except ModelError as exc:
            raise ModelError(f"{q.name}: {exc}") from exc
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


def load_file(path: Path, program: str) -> ProgramModel:
    text = path.read_text(encoding="utf-8", errors="replace")
    fixed = detect_fixed(text)
    try:
        items = _inline_copies(sentences(normalize(text, fixed)), path.parent)
    except OSError as exc:
        raise ModelError(str(exc)) from exc
    files: dict[str, FileDef] = {}
    fd_items: dict[str, list[tuple[int, str]]] = {}
    sd_names: set[str] = set()
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
        elif section == "FILE" and re.match(r"^(FD|SD)\s", up):
            current_fd = re.match(r"^(?:FD|SD)\s+([A-Z0-9-]+)", up).group(1)
            if up.startswith("SD"):
                sd_names.add(current_fd)
            fd_items.setdefault(current_fd, [])
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
    for m in re.finditer(r"\bCALL\s+['\"]([A-Za-z0-9_-]+)['\"]", proc_text, re.I):
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
    model = ProgramModel(program, path, fixed, pid.strip("'\"").upper(), list(files.values()), fd_items, ws, proc, ws_records, accepts,
                         [], sorted(set(unsupported)), linkage, using, initial, [], calls)
    if not proc:
        raise ModelError("No PROCEDURE DIVISION statements were found.")
    missing = [u for u in using if u not in {r.name for r in linkage}]
    if missing:
        raise ModelError(f"PROCEDURE DIVISION USING names {', '.join(missing)}, which is not a 01 or 77 item in the LINKAGE SECTION.")
    model.notes += source_fixes(text, fixed)[1]
    for f in model.files:
        if f.organization == "line" and any(lf.item.usage != "display" for r in f.records for lf in leaves(r)):
            model.notes.append(f"{f.name} is a text (LINE SEQUENTIAL) file but its record has binary or packed fields.")
        for key in [f.record_key, f.relative_key, *[k for k, _ in f.alt_keys]]:
            if key and f.organization == "indexed" and key != f.relative_key and not any(it.name == key for r in f.records for it in walk(r)):
                raise ModelError(f"The key {key} of indexed file {f.name} must be a field of its record.")
    return model
