"""COPY and REPLACE, read the way GnuCOBOL reads them (seance.copybook). Each program is checked twice against
GnuCOBOL: its text after COPY and REPLACE must be cobc -E's word for word, and the translated Python must give the
compiled COBOL's output byte for byte."""
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

from seance.cobol_src import detect_fixed, normalize, read_lines
from seance.copybook import CopyError, Rule, _Replacer, expand, parse, text_words
from seance.model import ModelError, copy_dirs, load_model
from seance.precompile import directive
from seance.recorder import cobc_available, cobc_path, cobol_env

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
needs_cobol = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def L(text: str = "") -> str:
    """A fixed-format line: code from column 8."""
    line = "       " + text
    assert len(line) <= 72, line
    return line


def _consecutive_quote_lines() -> list[str]:
    """A literal whose closing quote falls on column 72, continued by a line that starts with two quotes: cobc reads
    the pair as one quote inside the literal."""
    head = '       01  WS-Q PIC X(40) VALUE "'
    first = head + "A" * (72 - len(head) - 1) + '"'
    assert len(first) == 72
    return [first, '      -    ""B".']


MAIN = "\n".join([
    L("IDENTIFICATION DIVISION."),
    L("PROGRAM-ID. COPYPROG."),
    L("AUTHOR. O'BRIEN AND SONS."),
    L('INSTALLATION. A "QUOTED" PLACE.'),
    L("    COPY NOTHERE."),
    L("ENVIRONMENT DIVISION."),
    L("INPUT-OUTPUT SECTION."),
    L("FILE-CONTROL."),
    L("    COPY SELOUT."),
    L("I-O-CONTROL."),
    L("    SAME RECORD AREA FOR OUT-A OUT-B."),
    L("DATA DIVISION."),
    L("FILE SECTION."),
    L("FD  OUT-A."),
    L("01  OUT-A-REC                       COPY PIC10."),
    L("FD  OUT-B."),
    L("01  OUT-B-REC."),
    L("    05  OUT-B-KEY  PIC X(4)."),
    L("    05  OUT-B-REST PIC X(6)."),
    L("WORKING-STORAGE SECTION."),
    L("    COPY TAGREC REPLACING ==:TAG:== BY ==WS==."),
    L("    COPY TAGREC REPLACING ==:TAG:== BY ==HOLD==."),
    L("01  WS-COUNT    PIC 9(4) VALUE 0."),
    # not right after a COPY: cobc 3.1.2 cannot compile a literal continued on the line after a COPY statement
    *_consecutive_quote_lines(),
    L('01  WS-TEXT     PIC X(20) VALUE "pig and dog".'),
    L("01  WS-PREFIX."),
    L("    COPY PREFIXED REPLACING LEADING ==OLD-== BY ==NEW-=="),
    L("                            TRAILING ==-X== BY ==-Y==."),
    L("PROCEDURE DIVISION."),
    L("MAIN-PARA."),
    L('    MOVE "ALPHA" TO WS-NAME'),
    L("    MOVE 12 TO WS-AMOUNT"),
    L("    MOVE WS-REC TO HOLD-REC"),
    L('    DISPLAY "HOLD " HOLD-NAME " " HOLD-AMOUNT'),
    L('    DISPLAY "FIELDS " NEW-FIELD-X NEW-OTHER KEEP-Y'),
    L('    DISPLAY "Q " WS-Q.'),
    L('    COPY STEPS REPLACING =="pig"== BY =="cow"=='),
    L("                         ==ADD 1== BY ==ADD 5==."),
    L("STEP-THREE."),
    L('    REPLACE ==SHOW-COUNT== BY ==DISPLAY "COUNT " WS-COUNT==.'),
    L("    SHOW-COUNT."),
    L("    REPLACE ALSO ==WS-COUNT== BY ==HOLD-AMOUNT==."),
    L("    SHOW-COUNT."),
    L('    DISPLAY "HOLD-AMOUNT " WS-COUNT.'),
    L("    REPLACE LAST OFF."),
    L("    SHOW-COUNT."),
    L('    REPLACE ==MOVE "A"'),
    "      *    a comment between the words of the pseudo-text",
    L('         TO WS-NAME== BY ==MOVE "REPLACED" TO WS-NAME=='),
    L("            ==1 TO WS-COUNT== BY ==9 TO WS-COUNT=="),
    L('            =="COPIED "== BY =="FROM COPY "==.'),
    L('    MOVE "A"'),
    "      *    a comment between the words of the program",
    L("        TO WS-NAME."),
    L('    DISPLAY "NAME " WS-NAME.'),
    L("    ADD 1 1 TO WS-COUNT."),
    L("    COPY SHOWNAME."),
    L("    REPLACE OFF."),
    L('    DISPLAY "AFTER " WS-COUNT.'),
    L("    COPY LIBTEXT OF SUBLIB."),
    L("    OPEN OUTPUT OUT-A OUT-B."),
    L('    MOVE "ABCDEFGHIJ" TO OUT-A-REC.'),
    L("    WRITE OUT-B-REC."),
    L('    MOVE "WXYZ" TO OUT-B-KEY.'),
    L("    WRITE OUT-A-REC."),
    L("    CLOSE OUT-A OUT-B."),
    L("    STOP RUN."),
]) + "\n"

COPYBOOKS = {
    "PIC10.cpy": L("    PIC X(10)."),
    "SELOUT.cpy": "\n".join([
        L('SELECT OUT-A ASSIGN TO "OUTA.DAT"'),
        L("    ORGANIZATION IS LINE SEQUENTIAL."),
        L('SELECT OUT-B ASSIGN TO "OUTB.DAT"'),
        L("    ORGANIZATION IS LINE SEQUENTIAL."),
    ]),
    "TAGREC.cpy": "\n".join([
        L("01  :TAG:-REC."),
        L("    05  :TAG:-NAME    PIC X(8)."),
        L("    05  :TAG:-AMOUNT  PIC 9(4)."),
    ]),
    "PREFIXED.cpy": "\n".join([
        L('    05  OLD-FIELD-X   PIC X(3) VALUE "ABC".'),
        L('    05  OLD-OTHER     PIC X(3) VALUE "DEF".'),
        L('    05  KEEP-X        PIC X(3) VALUE "GHI".'),
    ]),
    "STEPS.cpy": "\n".join([
        L("STEP-ONE."),
        L("    ADD 1 TO WS-COUNT"),
        L('    INSPECT WS-TEXT REPLACING ALL "pig" BY "PIG"'),
        L('    DISPLAY "TEXT " WS-TEXT.'),
        L("STEP-TWO."),
        L("    COPY INNER."),
    ]),
    "INNER.cpy": "\n".join([
        L("    ADD 1 TO WS-COUNT"),
        L('    DISPLAY "INNER pig " WS-COUNT.'),
    ]),
    "SHOWNAME.cpy": L('    DISPLAY "COPIED " WS-NAME.'),
    "LIBTEXT.cpy": L('    DISPLAY "FROM THE PROGRAM FOLDER".'),
    "SUBLIB/LIBTEXT.cpy": L('    DISPLAY "FROM LIBRARY SUBLIB".'),
}


def _write(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in COPYBOOKS.items():
        p = folder / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n", encoding="utf-8")
    main = folder / "stp.cbl"
    main.write_text(MAIN, encoding="utf-8")
    return main


def _words(lines):
    out = []
    for t in lines:
        for w in text_words(t):
            w = w.strip()
            if w and w not in (",", ";"):
                out.append(w if w[0] in "\"'" else w.upper())
    return out


@needs_cobol
def test_text_after_copy_and_replace_is_cobcs_word_for_word(tmp_path):
    main = _write(tmp_path / "src")
    out = tmp_path / "stp.i"
    proc = subprocess.run([cobc_path(), "-E", "-fixed", "-I", str(main.parent), str(main), "-o", str(out)],
                          capture_output=True, text=True, env=cobol_env())
    assert proc.returncode == 0, proc.stderr
    theirs = [ln for ln in out.read_text(encoding="latin-1").splitlines() if not ln.startswith("#line")]
    text = main.read_text(encoding="utf-8")
    mine = [ln.text for ln in expand(read_lines(text, detect_fixed(text), False), copy_dirs(main.parent), False)
            if not ln.comment and directive(ln.text) is None]
    assert _words(mine) == _words(theirs)


@needs_cobol
def test_copy_and_replace_program_matches_gnucobol(tmp_path, monkeypatch):
    stress = _load("stress_translate")
    _write(tmp_path / "legacy" / "stp")
    src = tmp_path / "main.cbl"
    src.write_text(MAIN, encoding="utf-8")
    result = stress.run_one(src, "stp", tmp_path)
    assert result["stage"] == "match", result


def test_copied_lines_point_at_the_copy_statement(tmp_path):
    main = _write(tmp_path / "legacy" / "stp")
    lines = normalize(main.read_text(encoding="utf-8"), True, copy_dirs(main.parent))
    copy_line = next(i for i, t in enumerate(MAIN.splitlines(), 1) if "COPY STEPS" in t)
    step_one = next(ln for ln in lines if ln.text.strip() == "STEP-ONE.")
    inner = next(ln for ln in lines if '"INNER pig "' in ln.text)
    assert step_one.number == copy_line and inner.number == copy_line  # nested copybooks too


def test_the_model_sees_copied_data_and_shared_record_areas(tmp_path):
    _write(tmp_path / "legacy" / "stp")
    model = load_model("stp", tmp_path)
    names = {it.name for r in model.ws_records for it in [r, *r.children]}
    assert {"WS-REC", "HOLD-REC", "WS-PREFIX"} <= names
    out_a, out_b = (next(f for f in model.files if f.name == n) for n in ("OUT-A", "OUT-B"))
    assert out_a.same_record and out_a.same_record == out_b.same_record


def test_a_missing_copybook_is_an_error_that_names_it(tmp_path):
    folder = tmp_path / "legacy" / "stp"
    folder.mkdir(parents=True)
    (folder / "stp.cbl").write_text("\n".join([
        L("IDENTIFICATION DIVISION."), L("PROGRAM-ID. STP."), L("DATA DIVISION."), L("WORKING-STORAGE SECTION."),
        L("    COPY NOSUCH."), L("PROCEDURE DIVISION."), L("    STOP RUN."), ""]), encoding="utf-8")
    with pytest.raises(ModelError, match=r"line 5: copybook NOSUCH was not found"):
        load_model("stp", tmp_path)


def test_a_copybook_that_copies_itself_is_refused(tmp_path):
    (tmp_path / "LOOP.cpy").write_text(L("COPY LOOP.") + "\n", encoding="utf-8")
    text = "\n".join([L("IDENTIFICATION DIVISION."), L("PROGRAM-ID. STP."), L("PROCEDURE DIVISION."), L("COPY LOOP."), ""])
    with pytest.raises(CopyError, match="copies itself"):
        normalize(text, True, [tmp_path])


def _replace(rules, text):
    rep = _Replacer()
    for w in text_words(text):
        rep.feed(w, 1, rules)
    rep.feed("\n", 1, rules)
    rep.flush()
    return "".join(w for w, _ in rep.out).strip()


def _rules(statement: str):
    stmt, _ = parse("REPLACE", statement)
    return stmt.rules


def test_replacing_compares_literals_without_regard_to_case_as_cobc_does():
    assert _replace(_rules('=="pig"== BY =="cow"==.'), 'MOVE "PIG" TO A "pig" "Pig"') == 'MOVE "cow" TO A "cow" "cow"'


def test_a_failed_partial_match_lets_every_held_word_go_unchanged():
    # the standard steps back one word and finds "1 TO X" in "ADD 1 1 TO X"; cobc does not
    assert _replace(_rules("==1 TO X== BY ==9 TO X==."), "ADD 1 1 TO X") == "ADD 1 1 TO X"
    assert _replace(_rules("==1 TO X== BY ==9 TO X==."), "ADD 1 TO X") == "ADD 9 TO X"


def test_replacement_text_is_not_compared_again():
    rules = _rules("==A== BY ==B== ==B== BY ==C==.")
    assert _replace(rules, "MOVE A TO B") == "MOVE B TO C"


def test_leading_and_trailing_change_part_of_one_word():
    rules = _rules("LEADING ==WS-== BY ==LS-== TRAILING ==-IN== BY ==-OUT==.")
    assert _replace(rules, "MOVE WS-A-IN TO B-IN WS-") == "MOVE LS-A-IN TO B-OUT LS-"


def test_colon_tags_are_words_between_separators():
    assert _replace(_rules("==:PFX:== BY ==CUST==."), "05 :PFX:-NAME PIC X.") == "05 CUST-NAME PIC X."


def test_statement_errors_say_what_is_wrong():
    with pytest.raises(CopyError, match="not closed"):
        parse("COPY", "X REPLACING ==A BY ==B==.")
    with pytest.raises(CopyError, match="no period"):
        parse("COPY", "X REPLACING A BY B")
    stmt, end = parse("COPY", 'ALTLB OF "../copyalt". MORE')
    assert (stmt.name, stmt.library) == ("ALTLB", "../copyalt") and 'ALTLB OF "../copyalt".'[end - 1] == "."


def test_comment_entries_are_left_out_like_cobc_leaves_them_out():
    text = "\n".join([L("IDENTIFICATION DIVISION."), L("PROGRAM-ID. P."), L("AUTHOR. O'BRIEN."), L("    STILL THE AUTHOR'S."),
                      L("DATE-WRITTEN. TODAY."), L("ENVIRONMENT DIVISION."), ""])
    kept = [ln.text.strip() for ln in normalize(text, True) if not ln.comment]
    assert kept == ["IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "ENVIRONMENT DIVISION."]


def test_a_literal_closed_on_column_72_continues_with_a_doubled_quote():
    text = "\n".join([L("IDENTIFICATION DIVISION."), L("PROGRAM-ID. P."), L("DATA DIVISION."), L("WORKING-STORAGE SECTION."),
                      *_consecutive_quote_lines(), ""])
    line = next(ln.text for ln in normalize(text, True) if "WS-Q" in ln.text)
    assert re.search(r'"A{38}""B"\.$', line), line
