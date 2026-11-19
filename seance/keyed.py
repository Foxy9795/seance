"""Indexed and relative files on the COBOL side.

GnuCOBOL keeps an indexed file in Berkeley DB format, which only COBOL can read and write. So a test case holds a
keyed file as plain fixed-length records, and two small generated COBOL programs move it in and out:
the loader WRITEs each record into the real indexed (or relative) file before the run, skipping any the file
refuses (a duplicate key), and the unloader reads it back in key order afterwards. The Python runtime keeps the
same records in memory and produces the same plain form, so the two can be compared byte for byte.

Relative files are written as a 9-digit slot number followed by the record, one per occupied slot.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .layout import walk
from .model import FileDef

SLOT_DIGITS = 9


def _key(f: FileDef, name: str) -> tuple[int, int]:
    for r in f.records:
        for it in walk(r):
            if it.name == name:
                return it.offset, it.size
    raise ValueError(f"key {name} is not in the record of {f.name}")


def _select(f: FileDef) -> str:
    if f.organization == "relative":
        return (f"           SELECT KEY-F ASSIGN TO KEYFILE ORGANIZATION RELATIVE\n"
                f"               ACCESS DYNAMIC RELATIVE KEY WS-SLOT FILE STATUS WS-ST.\n")
    lines = [f"           SELECT KEY-F ASSIGN TO KEYFILE ORGANIZATION INDEXED",
             f"               ACCESS DYNAMIC RECORD KEY K0"]
    for i, (_, dups) in enumerate(f.alt_keys, start=1):
        lines.append(f"               ALTERNATE RECORD KEY K{i}" + (" WITH DUPLICATES" if dups else ""))
    lines.append("               FILE STATUS WS-ST.")
    return "\n".join(lines) + "\n"


def _fd(f: FileDef) -> str:
    out = [f"       FD  KEY-F.", f"       01  K-REC PIC X({f.size})."]
    if f.organization == "indexed":
        for i, name in enumerate([f.record_key] + [k for k, _ in f.alt_keys]):
            off, size = _key(f, name)
            out.append(f"       01  K{i}-REC.")
            if off:
                out.append(f"           05 FILLER PIC X({off}).")
            out.append(f"           05 K{i} PIC X({size}).")
    return "\n".join(out) + "\n"


def loader_source(f: FileDef) -> str:
    move = "               ADD 1 TO WS-SLOT\n" if f.organization == "relative" else ""
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. KLOAD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEQ-F ASSIGN TO SEQFILE ORGANIZATION SEQUENTIAL.
{_select(f)}       DATA DIVISION.
       FILE SECTION.
       FD  SEQ-F.
       01  SEQ-REC PIC X({f.size + (SLOT_DIGITS if f.organization == 'relative' else 0)}).
{_fd(f)}       WORKING-STORAGE SECTION.
       01  WS-ST   PIC XX.
       01  WS-EOF  PIC X VALUE 'N'.
       01  WS-SLOT PIC 9({SLOT_DIGITS}) VALUE 0.
       PROCEDURE DIVISION.
           OPEN INPUT SEQ-F OUTPUT KEY-F
           PERFORM UNTIL WS-EOF = 'Y'
               READ SEQ-F AT END MOVE 'Y' TO WS-EOF
               NOT AT END
{_load_body(f, move)}               END-READ
           END-PERFORM
           CLOSE SEQ-F KEY-F
           STOP RUN.
"""


def _load_body(f: FileDef, move: str) -> str:
    if f.organization == "relative":
        return (f"                   MOVE SEQ-REC(1:{SLOT_DIGITS}) TO WS-SLOT\n"
                f"                   MOVE SEQ-REC({SLOT_DIGITS + 1}:{f.size}) TO K-REC\n"
                "                   WRITE K-REC INVALID KEY CONTINUE END-WRITE\n")
    return "                   WRITE K-REC FROM SEQ-REC INVALID KEY CONTINUE END-WRITE\n"


def unloader_source(f: FileDef) -> str:
    rel = f.organization == "relative"
    out_size = f.size + (SLOT_DIGITS if rel else 0)
    put = ("                   MOVE WS-SLOT TO SEQ-REC(1:9)\n"
           f"                   MOVE K-REC TO SEQ-REC({SLOT_DIGITS + 1}:{f.size})\n" if rel else "                   MOVE K-REC TO SEQ-REC\n")
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. KDUMP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEQ-F ASSIGN TO SEQFILE ORGANIZATION SEQUENTIAL.
{_select(f)}       DATA DIVISION.
       FILE SECTION.
       FD  SEQ-F.
       01  SEQ-REC PIC X({out_size}).
{_fd(f)}       WORKING-STORAGE SECTION.
       01  WS-ST   PIC XX.
       01  WS-EOF  PIC X VALUE 'N'.
       01  WS-SLOT PIC 9({SLOT_DIGITS}) VALUE 0.
       PROCEDURE DIVISION.
           OPEN INPUT KEY-F OUTPUT SEQ-F
           IF WS-ST NOT = '00' AND WS-ST NOT = '05'
               CLOSE SEQ-F
               STOP RUN
           END-IF
           PERFORM UNTIL WS-EOF = 'Y'
               READ KEY-F NEXT RECORD AT END MOVE 'Y' TO WS-EOF
               NOT AT END
{put}                   WRITE SEQ-REC
               END-READ
           END-PERFORM
           CLOSE SEQ-F KEY-F
           STOP RUN.
"""


def tools(f: FileDef, build_dir: Path, cobc: str, env: dict) -> tuple[Path, Path]:
    """Compile (once) the loader and unloader for this file's layout."""
    exe = ".exe" if os.name == "nt" else ""
    stem = "".join(c if c.isalnum() else "_" for c in f.assign)
    out = []
    for kind, source in (("load", loader_source(f)), ("dump", unloader_source(f))):
        src = build_dir / "keyed" / f"k{kind}_{stem}.cbl"
        target = src.with_suffix(exe)
        src.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or not src.exists() or src.read_text(encoding="utf-8") != source:
            src.write_text(source, encoding="utf-8")
            proc = subprocess.run([cobc, "-x", "-free", "-o", str(target), str(src)], capture_output=True, text=True, env=env)
            if proc.returncode != 0:
                raise RuntimeError(f"could not build the {kind}er for {f.assign}: {proc.stderr.strip()[:300]}")
        out.append(target)
    return out[0], out[1]


def load(loader: Path, seq_bytes: bytes, target: Path, work: Path, env: dict) -> None:
    seq = work / f"_{target.name}.seq"
    seq.write_bytes(seq_bytes)
    subprocess.run([str(loader)], cwd=work, env={**env, "DD_SEQFILE": str(seq), "DD_KEYFILE": str(target)}, capture_output=True, timeout=60)
    seq.unlink()


def dump(unloader: Path, target: Path, work: Path, env: dict) -> bytes | None:
    if not target.exists():
        return None
    seq = work / f"_{target.name}.out"
    subprocess.run([str(unloader)], cwd=work, env={**env, "DD_SEQFILE": str(seq), "DD_KEYFILE": str(target)}, capture_output=True, timeout=60)
    data = seq.read_bytes() if seq.exists() else b""
    if seq.exists():
        seq.unlink()
    return data
