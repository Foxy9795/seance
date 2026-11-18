"""Understand a legacy program well enough to run it: its files, record layouts and source format."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .cobol_src import detect_fixed, normalize, sentences
from .copybook import CopybookError, Layout, parse_items

ROOT = Path(__file__).resolve().parent.parent
COPY_EXTENSIONS = (".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB", "")


class ModelError(ValueError):
    """The program uses something Séance cannot run yet. The message says what, and what to try."""


@dataclass
class IOFile:
    name: str  # name used in SELECT / FD / OPEN
    assign: str  # external name from ASSIGN TO
    literal: bool  # ASSIGN TO "name" (a real file name) as opposed to a DD name
    organization: str  # "line" (LINE SEQUENTIAL) or "record" (fixed-length records, no newlines)
    layout: Layout | None = None


@dataclass
class ProgramModel:
    name: str
    path: Path
    fixed: bool
    input: IOFile
    output: IOFile
    notes: list[str] = field(default_factory=list)
    ws_items: list[tuple[int, str]] = field(default_factory=list)  # WORKING-STORAGE data descriptions
    proc_items: list[tuple[int, str]] = field(default_factory=list)  # PROCEDURE DIVISION sentences, original case
    fd_items: dict[str, list[tuple[int, str]]] = field(default_factory=dict)  # FD name -> its data descriptions
    program_id: str = ""

    @property
    def in_layout(self) -> Layout:
        return self.input.layout  # type: ignore[return-value]

    @property
    def out_layout(self) -> Layout:
        return self.output.layout  # type: ignore[return-value]

    @property
    def compile_flags(self) -> list[str]:
        return ["-fixed" if self.fixed else "-free"]


def _inline_copies(items: list[tuple[int, str]], include_dir: Path, depth: int = 0) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line_no, text in items:
        m = re.match(r"^COPY\s+([A-Z0-9_-]+)(?:\s+(?:OF|IN)\s+\S+)?(\s+REPLACING\b.*)?$", text.strip(), re.I)
        if not m:
            out.append((line_no, text))
            continue
        if m.group(2):
            raise ModelError(f"line {line_no}: COPY ... REPLACING is not supported yet. Write the copybook with the final names.")
        if depth > 5:
            raise ModelError(f"line {line_no}: COPY statements are nested too deeply.")
        name = m.group(1)
        found = next((include_dir / f"{name}{ext}" for ext in COPY_EXTENSIONS if (include_dir / f"{name}{ext}").is_file()), None)
        if not found:
            raise ModelError(f"line {line_no}: copybook {name} was not found next to the program. Add it as a copybook named {name}.")
        text_cp = found.read_text(encoding="utf-8", errors="replace")
        out.extend(_inline_copies(sentences(normalize(text_cp)), include_dir, depth + 1))
    return out


_SELECT = re.compile(r"^SELECT\s+(?:OPTIONAL\s+)?([A-Z0-9-]+)\s+ASSIGN\s+(?:TO\s+)?(.*)$", re.I | re.S)


def _parse_select(text: str, line_no: int) -> IOFile:
    m = _SELECT.match(text.strip())
    if not m:
        raise ModelError(f"line {line_no}: cannot read this SELECT: {text.strip()[:70]!r}")
    name, rest = m.group(1).upper(), m.group(2).strip()
    rest = re.sub(r"^(?:EXTERNAL|DYNAMIC)\s+", "", rest, flags=re.I)
    rest = re.sub(r"^(?:DISK|PRINTER|[A-Z]+-S-)\s+", "", rest, flags=re.I) if re.match(r"^(?:DISK|PRINTER)\s", rest, re.I) else rest
    tok = re.match(r"\"([^\"]*)\"|'([^']*)'|([A-Z0-9_-]+)", rest, re.I)
    if not tok:
        raise ModelError(f"line {line_no}: cannot find the file name in ASSIGN for {name}.")
    literal = tok.group(1) is not None or tok.group(2) is not None
    assign = next(g for g in tok.groups() if g is not None)
    upper = rest.upper()
    if re.search(r"ORGANI[SZ]ATION\s+(?:IS\s+)?(INDEXED|RELATIVE)", upper):
        raise ModelError(f"{name}: indexed and relative files are not supported yet. Séance supports sequential files.")
    org = "line" if re.search(r"LINE\s+SEQUENTIAL", upper) else "record"
    return IOFile(name, assign, literal, org)


def _opened(proc_text: str, mode: str, files: dict[str, IOFile]) -> list[str]:
    found: list[str] = []
    for m in re.finditer(rf"\bOPEN\s+((?:INPUT|OUTPUT|I-O|EXTEND)\b.*?)(?=\bOPEN\b|$)", proc_text, re.I | re.S):
        words = re.findall(r"[A-Z0-9-]+", m.group(1).upper())
        current = None
        for w in words:
            if w in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                current = w
            elif w in files and current:
                if current == mode or (mode == "OUTPUT" and current == "EXTEND"):
                    found.append(w)
            else:
                break  # first word that is neither a keyword nor a known file ends the OPEN
    return list(dict.fromkeys(found))


def load_model(program: str, root: Path = ROOT) -> ProgramModel:
    path = root / "legacy" / program / f"{program}.cbl"
    text = path.read_text(encoding="utf-8", errors="replace")
    fixed = detect_fixed(text)
    items = _inline_copies(sentences(normalize(text, fixed)), path.parent)

    files: dict[str, IOFile] = {}
    fd_items: dict[str, list[tuple[int, str]]] = {}
    section = ""
    current_fd = ""
    proc: list[str] = []
    ws: list[tuple[int, str]] = []
    proc_raw: list[tuple[int, str]] = []
    for line_no, s in items:
        up = s.upper().strip()
        if re.match(r"^(FILE|WORKING-STORAGE|LOCAL-STORAGE|LINKAGE)\s+SECTION$", up):
            section, current_fd = up.split()[0], ""
            continue
        if re.match(r"^PROCEDURE\s+DIVISION", up):
            section = "PROCEDURE"
            proc.append(up)
            continue
        if re.match(r"^FILE-CONTROL$", up):
            section = "FILE-CONTROL"
            continue
        if re.match(r"^(IDENTIFICATION|ID|ENVIRONMENT|DATA)\s+DIVISION$|^(INPUT-OUTPUT|CONFIGURATION)\s+SECTION$", up):
            continue
        if section == "FILE-CONTROL" and up.startswith("SELECT"):
            f = _parse_select(s, line_no)
            files[f.name] = f
        elif section == "FILE" and re.match(r"^(FD|SD)\s", up):
            current_fd = re.match(r"^(?:FD|SD)\s+([A-Z0-9-]+)", up).group(1)
            fd_items.setdefault(current_fd, [])
        elif section == "FILE" and current_fd and re.match(r"^\d{1,2}\s", up):
            fd_items[current_fd].append((line_no, s))
        elif section == "WORKING-STORAGE" and re.match(r"^\d{1,2}\s", up):
            ws.append((line_no, s))
        elif section == "PROCEDURE":
            proc.append(up)
            proc_raw.append((line_no, s))

    if not files:
        raise ModelError("No SELECT ... ASSIGN found. Séance needs a program that reads one file and writes one file.")
    proc_text = " ".join(proc)
    ins, outs = _opened(proc_text, "INPUT", files), _opened(proc_text, "OUTPUT", files)
    if len(ins) != 1 or len(outs) != 1:
        raise ModelError(
            f"Séance runs programs with exactly one input file and one output file. This one opens input {ins or 'none'} and output {outs or 'none'}."
        )
    notes: list[str] = []
    extra = [n for n in files if n not in (ins[0], outs[0])]
    if extra:
        raise ModelError(f"The program also uses file(s) {', '.join(extra)}. Séance supports one input and one output file for now.")

    for f in (files[ins[0]], files[outs[0]]):
        if f.name not in fd_items or not fd_items[f.name]:
            raise ModelError(f"No FD record description found for {f.name}.")
        try:
            layouts = parse_items(fd_items[f.name])
        except CopybookError as exc:
            raise ModelError(str(exc)) from exc
        f.layout = layouts[0]
        if len(layouts) > 1:
            notes.append(f"{f.name} has {len(layouts)} record descriptions. Séance uses the first, {layouts[0].record_name}.")
    pid = next((re.sub(r"[.\s].*$", "", s.split(None, 1)[1]) for _, s in items if re.match(r"^PROGRAM-ID\b", s.strip(), re.I) and len(s.split()) > 1), program.upper())
    return ProgramModel(program, path, fixed, files[ins[0]], files[outs[0]], notes, ws, proc_raw, fd_items, pid.strip("'\"").upper())
