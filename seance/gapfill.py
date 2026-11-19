"""Close the gaps that mutation testing finds.

A planted bug that survives means no saved record tells the original Python from the changed copy. For each
survivor this module looks for an input that does:

1. It watches the changed comparison while the original runs, and measures how far the input is from the
   point where the change would matter (for `<=` changed to `<` that is "both sides equal", for a constant
   changed from 1500 to 1501 it is "a value between 1500 and 1501").
2. It starts from the saved records, then walks each numeric field toward that point, one field at a time.
   When no saved record reaches the code, it starts from the same random inputs the random check uses.
3. Any input on which the original and the changed copy differ is shrunk to a few plain records, run through
   the real COBOL, and, if the COBOL agrees with the original Python, saved as a new test set (`gap-...`).
   If the COBOL disagrees, the Python has a real bug the saved records missed. That is reported, not saved.
4. A change that is reached exactly at its edge on several different inputs without ever changing the output
   is reported as "equivalent", with the evidence. A change nothing reaches, or that the budget ran out on,
   is reported as "needs human review".

Each survivor is searched in its own process with a time limit, because a changed copy can loop forever.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import operator
import random
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace

from .cases import Case, Result, apply_links, compare, file_records, key_links, pack_file, run_cobol, run_python, save_set, set_dir, set_names, spec_of, load_set, _units
from .codec import decode
from .layout import leaves
from .model import ProgramModel
from .mutate import _SWAP_TEXT, _SYMBOL, WORKERS, Site, _resolve, apply, find_sites, run_mutants
from .recorder import ROOT, cobol_env, compile_legacy, get_model

BIG = Decimal(10) ** 40  # distance for "this input does not reach the code at all"
EPS = Decimal("1e-9")  # distance for "inside the window's edge but not yet changing anything"
EQUIVALENT_AFTER = 4  # different inputs that hit the edge with identical output before we call a change equivalent
RUN_LIMIT = 4.0  # seconds one run of the Python may take before it counts as hung
SITE_SECONDS = 40  # default time per survivor
SET_PREFIX = "gap-"

_OPS = {"==": operator.eq, "!=": operator.ne, ">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le}
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


class _Found(Exception):
    pass


class _OutOfBudget(Exception):
    pass


# ---------------------------------------------------------------- an input, as editable values

@dataclass
class State:
    rows: dict[str, list[dict[int, object]]]  # input file name -> records as field values, for files that round-trip
    raw: dict[str, bytes]  # ASSIGN name -> bytes, for files kept exactly as they are
    stdin: list[str]

    def copy(self) -> "State":
        return State({k: [dict(r) for r in v] for k, v in self.rows.items()}, dict(self.raw), list(self.stdin))


def _parse_rows(f, data: bytes) -> list[dict[int, object]] | None:
    """Field values of every record, or None when the bytes do not survive decoding and encoding again."""
    try:
        lv = [(i, lf) for i, lf in enumerate(leaves(f.record)) if lf.name != "FILLER"]
        rows = []
        for unit in _units(f, data):
            unit = unit.ljust(f.size, b" ")
            rows.append({i: decode(spec_of(lf.item), unit[lf.offset:lf.offset + lf.width]) for i, lf in lv})
        return rows if pack_file(f, file_records(f, rows)) == data else None
    except Exception:
        return None


def state_of(model: ProgramModel, case: Case) -> State:
    rows: dict[str, list] = {}
    raw = dict(case.files)
    for f in model.inputs:
        if f.record is None or f.assign not in case.files:
            continue
        parsed = _parse_rows(f, case.files[f.assign])
        if parsed is not None:
            rows[f.name] = parsed
            raw.pop(f.assign, None)
    return State(rows, raw, list(case.stdin))


def case_of(model: ProgramModel, st: State) -> Case:
    case = Case(files=dict(st.raw), stdin=list(st.stdin))
    for f in model.inputs:
        if f.name in st.rows and f.record is not None:
            recs = file_records(f, st.rows[f.name])
            case.records[f.assign] = recs
            case.files[f.assign] = pack_file(f, recs)
    return case


class Coord:
    """One numeric value that can be moved: a field of a record, or a console line holding a number."""

    __slots__ = ("where", "file", "row", "key", "digits", "scale", "signed")

    def __init__(self, where: str, file: str, row: int, key: int, digits: int, scale: int, signed: bool):
        self.where, self.file, self.row, self.key, self.digits, self.scale, self.signed = where, file, row, key, digits, scale, signed

    def get(self, st: State) -> Decimal:
        return Decimal(st.rows[self.file][self.row][self.key]) if self.where == "row" else Decimal(st.stdin[self.row].strip())

    def put(self, st: State, v: Decimal) -> None:
        if self.where == "row":
            st.rows[self.file][self.row][self.key] = v
        else:
            st.stdin[self.row] = format(v.quantize(Decimal(1).scaleb(-self.scale)), "f")

    def moves(self, cur: Decimal):
        unit = Decimal(1).scaleb(-self.scale)
        top = Decimal(10) ** (self.digits - self.scale) - unit
        low = -top if self.signed else Decimal(0)
        seen = set()
        for k in range(self.digits):
            for sign in (1, -1):
                v = min(max(cur + sign * unit * 10**k, low), top)
                if v != cur and v not in seen:
                    seen.add(v)
                    yield v

    def clamp(self, v: Decimal) -> Decimal:
        unit = Decimal(1).scaleb(-self.scale)
        top = Decimal(10) ** (self.digits - self.scale) - unit
        return min(max(v, -top if self.signed else Decimal(0)), top)

    def random_value(self, rng: random.Random) -> Decimal:
        unit = Decimal(1).scaleb(-self.scale)
        top = 10**self.digits - 1
        pick = rng.random()
        n = rng.choice([0, 1, top]) if pick < 0.1 else rng.randrange(0, 10 ** min(self.digits, 4)) if pick < 0.6 else rng.randrange(0, top + 1)
        if self.signed and rng.random() < 0.25:
            n = -n
        return Decimal(n) * unit


def numeric_coords(model: ProgramModel, st: State) -> list[Coord]:
    out = []
    by_file = {f.name: leaves(f.record) for f in model.inputs if f.record is not None}
    for fname, rows in st.rows.items():
        lv = by_file[fname]
        for r, row in enumerate(rows):
            for i, v in row.items():
                it = lv[i].item
                if it.kind == "num" and isinstance(v, Decimal):
                    out.append(Coord("row", fname, r, i, it.digits, it.scale, it.signed))
    for n, line in enumerate(st.stdin):
        if _NUMBER.fullmatch(line.strip()):
            frac = line.strip().partition(".")[2]
            out.append(Coord("stdin", "", n, 0, 9, len(frac), True))
    return out


# ---------------------------------------------------------------- watching the changed spot while the original runs

def _num(x) -> Decimal | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (Decimal, int)):
        return Decimal(x)
    return None


class _Probe(ast.NodeTransformer):
    """Route every comparison on one line through a recorder that returns the same answer."""

    def __init__(self, line: int):
        self.line = line

    def visit_Compare(self, node):
        self.generic_visit(node)
        if node.lineno == self.line and len(node.ops) == 1 and type(node.ops[0]) in _SYMBOL:
            call = ast.Call(func=ast.Name("_sx_cmpr", ast.Load()),
                            args=[ast.Constant(_pid(node)), node.left, ast.Constant(_SYMBOL[type(node.ops[0])]), node.comparators[0]], keywords=[])
            return ast.copy_location(call, node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
        if node.lineno == self.line and name == "cmp" and len(node.args) == 3 and isinstance(node.args[1], ast.Constant) and node.args[1].value in _SWAP_TEXT:
            node.args = [ast.Constant(_pid(node)), node.func, *node.args]
            node.func = ast.Name("_sx_cmp", ast.Load())
        return node


def _pid(node) -> str:
    return f"{node.lineno}:{node.col_offset}"


def _insert_hit(tree: ast.Module, line: int) -> None:
    """Put a call that records "reached" in front of the innermost statement that holds `line`."""
    done = False

    def process(body: list) -> None:
        nonlocal done
        i = 0
        while i < len(body) and not done:
            s = body[i]
            for name in ("body", "orelse", "finalbody"):
                sub = getattr(s, name, None)
                if isinstance(sub, list):
                    process(sub)
            for h in getattr(s, "handlers", []):
                process(h.body)
            if done:
                return
            compound = hasattr(s, "body") and isinstance(s.body, list) and s.body
            last = (s.body[0].lineno - 1) if compound else s.end_lineno
            if s.lineno <= line <= last:
                body.insert(i, ast.Expr(ast.Call(ast.Name("_sx_hit", ast.Load()), [], [])))
                done = True
                return
            i += 1

    process(tree.body)


@dataclass
class Eval:
    usable: bool = True
    reached: bool = False
    flipped: bool = False
    dist: Decimal = BIG
    edge: bool = False  # a comparison on the changed line really did give a different answer
    hung: bool = False  # the changed copy never finished on this input
    differs: bool = False
    orig: Result | None = None
    mut: Result | None = None

    @property
    def score(self) -> Decimal:
        return Decimal(0) if self.flipped else (self.dist if self.reached else BIG)


class Searcher:
    """Searches for an input on which the original and one changed copy behave differently."""

    def __init__(self, program: str, implementation: str, site: Site, root: Path = ROOT, budget: int = 800, seconds: float = SITE_SECONDS, seed: int = 11):
        self.program, self.site, self.root, self.budget = program, site, root, budget
        self.deadline = time.monotonic() + seconds
        self.rng = random.Random(seed)
        self.model = get_model(program, root)
        path = root / (implementation.replace(".", "/") + ".py")
        self.source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(self.source)
        self.log: list[tuple[bool, Decimal]] = []
        self.hits = 0
        self.evals = 0
        self.hung = 0
        self.flips: dict[str, State] = {}
        self.reached_any = False
        node = _resolve(tree, site.path[:-1] if site.kind == "cmp" else site.path)
        self.pid = _pid(node) if site.kind in ("cmp", "compare") else None
        self.const = (Decimal(site.before), Decimal(site.after)) if site.kind == "constant" else None
        self.orig = self._load(self._instrument(tree), path)
        self.mutant = self._load(apply(tree, site), path)
        from .hints import value_hints

        self.hints = value_hints(self.model)

    # -- building the two programs

    def _instrument(self, tree: ast.Module) -> ast.Module:
        import copy

        probe = copy.deepcopy(tree)
        _Probe(self.site.line).visit(probe)
        if self.site.kind not in ("cmp", "compare"):
            _insert_hit(probe, self.site.line)
        return ast.fix_missing_locations(probe)

    def _load(self, tree: ast.Module, path: Path) -> SimpleNamespace:
        ns = {"__name__": "seance_gapfill", "__file__": str(path), "_sx_cmp": self._probe_cmp, "_sx_cmpr": self._probe_cmpr, "_sx_hit": self._hit}
        exec(compile(ast.unparse(tree), str(path), "exec"), ns)
        return SimpleNamespace(main=ns["main"])

    # -- what the probes record

    def _hit(self) -> None:
        self.hits += 1

    def _probe_cmp(self, pid, func, a, op, b):
        res = func(a, op, b)
        prog = getattr(func, "__self__", None)
        try:
            na, nb = prog._operand(a)[0], prog._operand(b)[0]
        except Exception:
            na = nb = None
        self._note(pid, lambda o, x, y: func(x, o, y), a, op, b, na, nb, res, literal=lambda x: _num(x) if not hasattr(x, "name") else None)
        return res

    def _probe_cmpr(self, pid, a, op, b):
        res = _OPS[op](a, b)
        self._note(pid, lambda o, x, y: _OPS[o](x, y), a, op, b, _num(a), _num(b), res, literal=_num)
        return res

    def _note(self, pid, cmp2, a, op, b, na, nb, res, literal) -> None:
        site = self.site
        if site.kind in ("cmp", "compare"):
            if pid != self.pid:
                return
            flipped = cmp2(site.after, a, b) != res
            dist = Decimal(0) if flipped else (abs(na - nb) if na is not None and nb is not None else Decimal(1))
            self.log.append((flipped, dist))
        elif site.kind == "constant" and self.const is not None:
            c0, c1 = self.const
            if literal(b) == c0:
                x, alt = na, cmp2(op, a, Decimal(site.after))
            elif literal(a) == c0:
                x, alt = nb, cmp2(op, Decimal(site.after), b)
            else:
                return
            flipped = alt != res
            lo, hi = min(c0, c1), max(c0, c1)
            gap = Decimal(0) if x is None else (lo - x if x < lo else x - hi if x > hi else Decimal(0))
            self.log.append((flipped, Decimal(0) if flipped else max(gap, EPS)))

    # -- running both

    def _guarded(self, mod: SimpleNamespace, case: Case) -> Result | None:
        box: list[Result] = []

        def go() -> None:
            try:
                box.append(run_python(mod, case))
            except BaseException as exc:  # a changed copy may end in ways run_python does not expect
                box.append(Result(error=f"{type(exc).__name__}: {exc}"))

        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(RUN_LIMIT)
        return box[0] if box else None

    def measure(self, st: State) -> Eval:
        self.evals += 1
        case = case_of(self.model, st)
        self.log.clear()
        self.hits = 0
        orig = self._guarded(self.orig, case)
        if orig is None:
            self.hung += 1
            return Eval(usable=False)
        ev = Eval(orig=orig)
        flips = [x for x in self.log if x[0]]
        ev.reached = bool(self.log) or self.hits > 0
        if self.log:
            ev.flipped = ev.edge = bool(flips)
            ev.dist = min(d for _, d in self.log)
        elif self.hits:
            ev.flipped, ev.dist = True, Decimal(0)  # no comparison to steer by: reaching the code is all there is
        if self.site.kind in ("cmp", "compare") and not ev.flipped:
            ev.mut = orig  # the changed comparison gave the same answer every time, so nothing downstream can differ
            return ev
        mut = self._guarded(self.mutant, case)
        if mut is None:  # the original finished and the changed copy never did: that tells them apart
            ev.mut, ev.differs, ev.hung = Result(error="the changed copy did not finish"), True, True
            return ev
        ev.mut, ev.differs = mut, mut != orig
        return ev

    def eval(self, st: State) -> Eval:
        if self.evals >= self.budget or time.monotonic() > self.deadline or self.hung >= 3:
            raise _OutOfBudget()
        ev = self.measure(st)
        if ev.usable and ev.differs:
            self.found = (st.copy(), ev)
            raise _Found()
        if ev.usable and ev.edge:
            self.flips.setdefault(_signature(self.model, st), st.copy())
        return ev

    # -- the search

    def pool(self) -> list[State]:
        out = []
        for name in set_names(self.program, self.root):
            case, _, _ = load_set(self.program, name, self.root)
            out.append(state_of(self.model, case))
        return out

    def explore(self, count: int) -> list[State]:
        """Random inputs from the generators the random check uses. Hypothesis only generates them, so the same run repeats."""
        from hypothesis import HealthCheck, Phase, given, settings

        from .verify import _case_strategy, _stdin

        links = key_links(self.model)
        drawn: list[State] = []

        @settings(max_examples=count, deadline=None, database=None, derandomize=True, suppress_health_check=list(HealthCheck), phases=[Phase.generate])
        @given(_case_strategy(self.model, self.hints))
        def collect(example):
            rows, seed, n = example
            rows = {k: [dict(r) for r in v] for k, v in rows.items()}
            apply_links(links, rows, random.Random(seed))
            drawn.append(State(rows, {}, _stdin(self.model, self.hints, seed, n)))

        collect()
        return drawn

    def trim(self, st: State, ev: Eval) -> tuple[State, Eval]:
        """Fewer records, while the input still reaches the spot at least as closely."""
        for fname in list(st.rows):
            while len(st.rows[fname]) > 1:
                n = len(st.rows[fname])
                for part in (st.rows[fname][: n // 2], st.rows[fname][n // 2:]):
                    cand = st.copy()
                    cand.rows[fname] = [dict(r) for r in part]
                    e = self.eval(cand)
                    if e.usable and e.reached and e.score <= ev.score:
                        st, ev = cand, e
                        break
                else:
                    break
        return st, ev

    def descend(self, st: State, ev: Eval, limit: int = 200) -> tuple[State, Eval]:
        """Move one numeric field at a time toward the point where the change matters."""
        start = self.evals
        improved = True
        while improved and ev.score > 0 and self.evals - start < limit:
            improved = False
            for c in numeric_coords(self.model, st):
                cur = c.get(st)
                best = None
                for v in c.moves(cur):
                    cand = st.copy()
                    c.put(cand, v)
                    e = self.eval(cand)
                    if e.usable and e.score < ev.score and (best is None or e.score < best[1].score):
                        best = (cand, e, v - cur)
                if best is None:
                    continue
                st, ev, delta = best
                improved = True
                while ev.score > 0 and self.evals - start < limit:  # keep going the same way while it helps
                    cand = st.copy()
                    nxt = c.clamp(c.get(cand) + delta)
                    if c.get(cand) == nxt:
                        break
                    c.put(cand, nxt)
                    e = self.eval(cand)
                    if not (e.usable and e.score < ev.score):
                        break
                    st, ev = cand, e
                if ev.score == 0:
                    break
        return st, ev

    def perturb(self, st: State) -> State:
        """A nearby input with a few values replaced, or a record added."""
        cand = st.copy()
        coords = numeric_coords(self.model, cand)
        if coords and self.rng.random() < 0.85:
            for c in self.rng.sample(coords, min(len(coords), self.rng.choice([1, 1, 2, 3]))):
                c.put(cand, c.random_value(self.rng))
        else:
            fname = self.rng.choice(sorted(cand.rows)) if cand.rows else None
            if fname and cand.rows[fname]:
                cand.rows[fname].append(dict(self.rng.choice(cand.rows[fname])))
        return cand

    def run(self) -> dict:
        try:
            return self._run()
        except _Found:
            st, ev = self.found
            if not ev.hung:  # shrinking a hang would wait out the time limit on every try
                small = self.minimize(st)
                again = self.measure(small)
                if again.usable and again.differs:
                    st, ev = small, again
            case = case_of(self.model, st)
            diffs, _ = compare(self.model, ev.orig, ev.mut)
            return {"status": "found", "evals": self.evals, "flips": len(self.flips), "files": {a: base64.b64encode(d).decode() for a, d in case.files.items()},
                    "stdin": case.stdin, "difference": diffs[0].to_dict() if diffs else None}
        except _OutOfBudget:
            return self._verdict()

    def _verdict(self) -> dict:
        reached = bool(self.flips) or self.reached_any
        if len(self.flips) >= EQUIVALENT_AFTER:
            status = "equivalent"
        elif not reached:
            status = "unreached"
        else:
            status = "open"
        return {"status": status, "evals": self.evals, "flips": len(self.flips)}

    def _run(self) -> dict:
        starts: list[tuple[Decimal, State, Eval]] = []

        def consider(st: State) -> None:
            ev = self.eval(st)
            if ev.usable and ev.reached:
                self.reached_any = True
                starts.append((ev.score, st, ev))

        for st in self.pool():
            consider(st)
        if not starts:
            for st in self.explore(300):
                consider(st)
                if len(starts) >= 4:
                    break
        starts.sort(key=lambda s: s[0])
        elite: list[State] = []
        for _, st, ev in starts[:4]:
            st, ev = self.trim(st, ev)
            st, ev = self.descend(st, ev)
            elite.append(st)
        if not elite:
            raise _OutOfBudget()
        while len(self.flips) < EQUIVALENT_AFTER:  # wander near what we have, then walk back to the edge
            base = self.rng.choice(list(self.flips.values()) + elite)
            cand = self.perturb(base)
            ev = self.eval(cand)
            if not (ev.usable and ev.reached):
                continue
            self.reached_any = True
            if ev.score > 0:
                cand, ev = self.descend(cand, ev, limit=60)
            elite.append(cand)
            elite = elite[-12:]
        raise _OutOfBudget()

    def minimize(self, st: State) -> State:
        """Smaller and plainer, while the two programs still differ."""
        def still(c: State) -> bool:
            ev = self.measure(c)
            return ev.usable and ev.differs

        for fname in list(st.rows):
            changed = True
            while changed and len(st.rows[fname]) > 1:
                changed = False
                for i in range(len(st.rows[fname])):
                    cand = st.copy()
                    del cand.rows[fname][i]
                    if still(cand):
                        st, changed = cand, True
                        break
        for i in range(len(st.stdin) - 1, -1, -1):
            cand = st.copy()
            del cand.stdin[i]
            if cand.stdin != st.stdin and still(cand):
                st = cand
        by_file = {f.name: leaves(f.record) for f in self.model.inputs if f.record is not None}
        for fname, rows in st.rows.items():
            for r in range(len(rows)):
                for i, v in list(rows[r].items()):
                    plain = Decimal(0) if by_file[fname][i].item.kind == "num" else ""
                    if v == plain:
                        continue
                    cand = st.copy()
                    cand.rows[fname][r][i] = plain
                    if still(cand):
                        st = cand
        return st


def _signature(model: ProgramModel, st: State) -> str:
    case = case_of(model, st)
    h = hashlib.sha1()
    for k in sorted(case.files):
        h.update(k.encode() + case.files[k])
    h.update("\n".join(case.stdin).encode())
    return h.hexdigest()


# ---------------------------------------------------------------- remembered verdicts

def _verdict_path(program: str, root: Path) -> Path:
    return root / "fixtures" / program / "gapfill.json"


def _source_hash(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def save_verdicts(program: str, source: str, verdicts: list[dict], root: Path = ROOT) -> None:
    path = _verdict_path(program, root)
    if verdicts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"source": _source_hash(source), "verdicts": verdicts}, indent=1), encoding="utf-8")
    elif path.exists():
        path.unlink()


def annotate(program: str, source: str, mutants: list[dict], root: Path = ROOT) -> int:
    """Attach remembered verdicts to surviving mutants. Returns how many are judged equivalent."""
    path = _verdict_path(program, root)
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if data.get("source") != _source_hash(source):
        return 0  # the Python changed since: the verdicts no longer apply
    known = {(v["kind"], v["line"], v["before"], v["after"]): v for v in data.get("verdicts", [])}
    equivalent = 0
    for m in mutants:
        v = known.get((m.get("kind"), m["line"], m.get("before"), m.get("after")))
        if v and not m["caught"]:
            m["verdict"], m["verdict_note"] = v["status"], v.get("note", "")
            equivalent += v["status"] == "equivalent"
    return equivalent


# ---------------------------------------------------------------- the whole job

NOTES = {
    "equivalent": "The comparison was tested at its edge on {flips} different inputs and the output never changed. "
                  "Most likely the change makes no difference. Confirm this against the COBOL source.",
    "unreached": "No input tried reached this code ({evals} tries). Check whether it can run at all, "
                 "or add a record that reaches it. Needs human review.",
    "open": "The code was reached but no input told the two apart in {evals} tries. Needs human review.",
}


def _search(program: str, implementation: str, m: dict, budget: int, seconds: int, root: Path) -> dict:
    env = cobol_env()
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    args = [sys.executable, "-m", "seance.gapfill", str(root), program, implementation, m["kind"], str(m["line"]), m["before"], m["after"], str(budget), str(seconds)]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=seconds + 25, env=env, cwd=root)
        lines = [x for x in proc.stdout.strip().splitlines() if x.startswith("{")]
        if proc.returncode == 0 and lines:
            return json.loads(lines[-1])
        return {"status": "open", "evals": 0, "flips": 0, "error": (proc.stderr.strip().splitlines() or ["the search stopped unexpectedly"])[-1]}
    except subprocess.TimeoutExpired:
        return {"status": "open", "evals": 0, "flips": 0, "error": "the search did not finish in time"}


def _name_for(program: str, line, root: Path) -> str:
    name, k = f"{SET_PREFIX}l{line}", 2
    while set_dir(program, name, root).exists():
        name, k = f"{SET_PREFIX}l{line}-{k}", k + 1
    return name


def fill_gaps(program: str, implementation: str | None = None, limit: int = 12, budget: int = 500, seconds: int = SITE_SECONDS,
              save: bool = True, again: bool = False, root: Path = ROOT) -> dict:
    from .verify import describe_case, load_implementation

    implementation = implementation or f"migrated.{program}"
    model = get_model(program, root)
    if model.sql_tables or model.cics:
        return {"error": "Gap filling does not cover SQL or CICS programs yet: their inputs are tables and screens, which the search cannot vary. "
                         "Add data for them by hand."}
    before = run_mutants(program, implementation, limit, root)
    if "error" in before:
        return before
    source = (root / (implementation.replace(".", "/") + ".py")).read_text(encoding="utf-8-sig")
    survivors = [m for m in before["mutants"] if not m["caught"]]
    results, saved, remembered = [], [], []
    if survivors:
        exe = compile_legacy(program, root)
        impl = load_implementation(implementation)
    to_search = [m for m in survivors if not (m.get("verdict") == "equivalent" and not again)]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:  # each search is its own process
        searched = dict(zip(map(id, to_search), pool.map(lambda m: _search(program, implementation, m, budget, seconds, root), to_search)))
    for m in survivors:
        base = {"line": m["line"], "cobol_line": m["cobol_line"], "change": m["change"], "kind": m["kind"], "before": m["before"], "after": m["after"]}
        if id(m) not in searched:
            results.append({**base, "status": "equivalent", "note": m.get("verdict_note", ""), "cached": True})
            remembered.append({**base, "status": "equivalent", "note": m.get("verdict_note", "")})
            continue
        found = searched[id(m)]
        status, info = found["status"], {"evals": found.get("evals", 0), "flips": found.get("flips", 0)}
        if status == "found":
            case = Case({a: base64.b64decode(d) for a, d in found["files"].items()}, list(found["stdin"]))
            for f in model.inputs:
                if f.assign in case.files:
                    case.records[f.assign] = _units(f, case.files[f.assign])
            expected = run_cobol(exe, model, case)
            actual = run_python(impl, case)
            diffs, _ = compare(model, expected, actual)
            shown = describe_case(model, case)
            if diffs:
                note = "Real mismatch: on this input the COBOL and the original Python disagree. The saved records never covered it. Needs human review."
                results.append({**base, **info, "status": "mismatch", "note": note, "inputs": shown, "diffs": [d.to_dict() for d in diffs[:5]], "difference": found["difference"]})
                remembered.append({**base, "status": "mismatch", "note": note})
                continue
            name = _name_for(program, m["cobol_line"] or m["line"], root) if save else None
            if name:
                label = f"Gap filler: {m['change']} (COBOL line {m['cobol_line'] or m['line']})"
                save_set(program, name, case, expected, label, root)
                saved.append(name)
            results.append({**base, **info, "status": "closed", "set": name, "inputs": shown, "difference": found["difference"],
                            "note": "A new test set now tells the original and the changed copy apart." if name else "Found an input that tells them apart (not saved)."})
        else:
            note = NOTES[status].format(**info)
            results.append({**base, **info, "status": status, "note": note, **({"error": found["error"]} if found.get("error") else {})})
            remembered.append({**base, "status": status, "note": note})
    if survivors:
        save_verdicts(program, source, remembered, root)
    after = run_mutants(program, implementation, limit, root) if survivors else before  # verdicts and new sets change the picture
    return {
        "program": program, "implementation": implementation,
        "before": {"caught": before["caught"], "total": before["total"]},
        "after": {"caught": after["caught"], "total": after["total"], "equivalent": after.get("equivalent", 0)},
        "saved": saved, "results": results, "strength": after,
    }


# ---------------------------------------------------------------- one survivor, in its own process

def _worker(argv: list[str]) -> int:
    import os

    root, program, implementation, kind, line, before, after, budget, seconds = argv
    sys.path.insert(0, root)
    wanted = [s for s in find_sites(ast.parse((Path(root) / (implementation.replace(".", "/") + ".py")).read_text(encoding="utf-8-sig")))
              if (s.kind, s.line, s.before, s.after) == (kind, int(line), before, after)]
    if not wanted:
        print(json.dumps({"status": "open", "evals": 0, "flips": 0, "error": "the planted bug is no longer in the code"}))
        return 0
    result = Searcher(program, implementation, wanted[0], Path(root), int(budget), float(seconds)).run()
    print(json.dumps(result), flush=True)
    os._exit(0)  # a changed copy that hung leaves a spinning thread behind; end the process without waiting for it


if __name__ == "__main__":
    raise SystemExit(_worker(sys.argv[1:]))
