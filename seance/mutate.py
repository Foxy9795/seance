"""Measure how strong the tests are: plant small bugs in the Python and see whether the check catches them.

Each mutant changes one thing: a comparison (> to >=), a ROUNDED flag, a constant (0.10 to 0.11), or + to -.
A mutant that survives means the saved records never exercise that spot, or the change makes no difference
there. Either way it points at a test to add. Only the saved records are replayed, so this is fast and does
not need the COBOL runtime.
"""

from __future__ import annotations

import ast
import copy
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .recorder import ROOT, cobol_env, get_model
from .verify import load_implementation, replay_sets

MUTANT_TIMEOUT = 10  # seconds per planted bug; a bug that makes the program hang is caught when this runs out
WORKERS = max(1, min(4, (os.cpu_count() or 2) // 2))  # planted bugs replayed side by side

WORKER = """
import sys
root, tmp, program, name = sys.argv[1:5]
sys.path[:0] = [root, tmp]
import importlib
from seance.recorder import get_model
from seance.verify import replay_sets
impl = importlib.import_module(name)
sets, _ = replay_sets(program, impl, get_model(program))
print(sum(s["differing"] for s in sets))
"""

_SWAP = {ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
_SWAP_TEXT = {">": ">=", ">=": ">", "<": "<=", "<=": "<", "==": "!=", "!=": "=="}
_SYMBOL = {ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<=", ast.Eq: "==", ast.NotEq: "!="}


@dataclass
class Site:
    kind: str
    line: int
    path: list  # how to reach the node: list of (field, index) steps from the module
    before: str
    after: str


@dataclass
class Mutant:
    line: int
    cobol_line: int | None
    change: str
    caught: bool
    failing: int
    kind: str = ""
    before: str = ""
    after: str = ""


def _bump(text: str) -> str | None:
    try:
        Decimal(text)
    except InvalidOperation:
        return None
    digits = [i for i, c in enumerate(text) if c.isdigit()]
    if not digits:
        return None
    i = digits[-1]
    return text[:i] + str((int(text[i]) + 1) % 10) + text[i + 1:]


def _walk(node, path):
    for name, value in ast.iter_fields(node):
        if isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, ast.AST):
                    yield item, path + [(name, i)]
                    yield from _walk(item, path + [(name, i)])
        elif isinstance(value, ast.AST):
            yield value, path + [(name, None)]
            yield from _walk(value, path + [(name, None)])


def _items(tree: ast.Module) -> dict[str, tuple]:
    """ITEMS from a translated draft (name -> runtime item spec), or {} for hand-written code."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ITEMS" for t in node.targets):
            try:
                return {k.value: v for k, v in zip(node.value.keys, (ast.literal_eval(_strip_calls(v)) for v in node.value.values))}
            except Exception:
                return {}
    return {}


def _strip_calls(node):
    """literal_eval cannot read D("1") or SPACE; replace them with plain constants."""
    class T(ast.NodeTransformer):
        def visit_Call(self, n):
            return ast.Constant(None)

        def visit_Name(self, n):
            return ast.Constant(None)
    return T().visit(copy.deepcopy(node))


def _rounding_cannot_matter(lam: ast.Lambda, target: str, items: dict) -> bool:
    """True when the value can never have more decimals than the target: only + and - of fields and constants
    whose scale is at most the target's. Then adding or removing ROUNDED changes nothing."""
    spec = items.get(target)
    if not spec:
        return False
    scale = spec[6]  # [record, offset, size, kind, usage, digits, scale, ...]
    for n in ast.walk(lam.body):
        if isinstance(n, ast.BinOp) and not isinstance(n.op, (ast.Add, ast.Sub)):
            return False
        if isinstance(n, ast.Call):
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            arg = n.args[0].value if n.args and isinstance(n.args[0], ast.Constant) else None
            if name == "n" and isinstance(arg, str):
                other = items.get(arg)
                if not other or other[6] > scale:
                    return False
            elif name in ("D", "Decimal") and isinstance(arg, str):
                if "." in arg and len(arg.split(".")[1]) > scale:
                    return False
            else:
                return False
    return True


def find_sites(tree: ast.Module) -> list[Site]:
    items = _items(tree)
    sites: list[Site] = []
    for node, path in _walk(tree, []):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _SWAP:
            sym = _SYMBOL[type(node.ops[0])]
            sites.append(Site("compare", line, path, sym, _SYMBOL[_SWAP[type(node.ops[0])]]))
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
            if name == "cmp" and len(node.args) == 3 and isinstance(node.args[1], ast.Constant) and node.args[1].value in _SWAP_TEXT:
                sites.append(Site("cmp", line, path + [("args", 1)], node.args[1].value, _SWAP_TEXT[node.args[1].value]))
            if name in ("D", "Decimal") and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                bumped = _bump(node.args[0].value)
                if bumped and node.args[0].value not in ("0", "1"):
                    sites.append(Site("constant", line, path + [("args", 0)], node.args[0].value, bumped))
            for k, kw in enumerate(node.keywords):
                if kw.arg == "rounded" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
                    sites.append(Site("rounded", line, path + [("keywords", k), ("value", None)], str(kw.value.value), str(not kw.value.value)))
        elif isinstance(node, ast.Tuple) and len(node.elts) == 3 and isinstance(node.elts[0], ast.Constant) and isinstance(node.elts[0].value, str) \
                and isinstance(node.elts[1], ast.Lambda) and isinstance(node.elts[2], ast.Constant) and isinstance(node.elts[2].value, bool):
            if not _rounding_cannot_matter(node.elts[1], node.elts[0].value, items):
                sites.append(Site("rounded", line, path + [("elts", 2)], str(node.elts[2].value), str(not node.elts[2].value)))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            sites.append(Site("arith", line, path, "+" if isinstance(node.op, ast.Add) else "-", "-" if isinstance(node.op, ast.Add) else "+"))
    return sites


def _resolve(tree, path):
    node = tree
    for name, idx in path:
        node = getattr(node, name)
        if idx is not None:
            node = node[idx]
    return node


def apply(tree: ast.Module, site: Site) -> ast.Module:
    mutant = copy.deepcopy(tree)
    node = _resolve(mutant, site.path)
    if site.kind == "compare":
        node.ops = [_SWAP[type(node.ops[0])]()]
    elif site.kind == "cmp":
        node.value = site.after
    elif site.kind == "constant":
        node.value = site.after
    elif site.kind == "rounded":
        node.value = not node.value
    elif site.kind == "arith":
        node.op = ast.Sub() if isinstance(node.op, ast.Add) else ast.Add()
    return ast.fix_missing_locations(mutant)


def _describe(site: Site) -> str:
    if site.kind in ("compare", "cmp"):
        return f"comparison {site.before} changed to {site.after}"
    if site.kind == "rounded":
        return "ROUNDED removed" if site.before == "True" else "ROUNDED added"
    if site.kind == "constant":
        return f"constant {site.before} changed to {site.after}"
    return f"{site.before} changed to {site.after}"


def _spread(sites: list[Site], limit: int) -> list[Site]:
    """Pick up to `limit` sites, at most one per kind and line, spread across the file."""
    seen, unique = set(), []
    for s in sites:
        key = (s.kind, s.line)
        if key not in seen:
            seen.add(key)
            unique.append(s)
    if len(unique) <= limit:
        return unique
    step = len(unique) / limit
    return [unique[int(i * step)] for i in range(limit)]


def _cobol_line(src_lines: list[str], line: int) -> int | None:
    """The COBOL line a Python line came from: its own # Lnn tag, or the nearest tagged line above it
    in the same function (helper lines such as a loop step belong to the statement that made them)."""
    for i in range(min(line, len(src_lines)) - 1, -1, -1):
        text = src_lines[i]
        tag = re.search(r"#\s*L(\d+)", text)
        if tag:
            return int(tag.group(1))
        if text.startswith("def "):
            return None
    return None


def run_mutants(program: str, implementation: str | None = None, limit: int = 12, root: Path = ROOT) -> dict:
    implementation = implementation or f"migrated.{program}"
    src_path = root / (implementation.replace(".", "/") + ".py")
    source = src_path.read_text(encoding="utf-8-sig")
    src_lines = source.splitlines()
    tree = ast.parse(source)
    model = get_model(program, root)
    base = load_implementation(implementation)
    baseline, base_diffs = replay_sets(program, base, model, root)
    if base_diffs or any(s["differing"] for s in baseline):
        return {"error": "The Python does not match the COBOL yet. Make the check pass first, then measure test strength."}

    sites = _spread(find_sites(tree), limit)
    results: list[Mutant] = []
    env = cobol_env()
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="seance_mut_") as tmp:
        def one(numbered: tuple[int, Site]) -> Mutant:
            i, site = numbered
            name = f"seance_mutant_{i}"
            Path(tmp, f"{name}.py").write_text(ast.unparse(apply(tree, site)), encoding="utf-8")
            # Each planted bug runs in its own process with a time limit: a bug can make a loop endless.
            try:
                proc = subprocess.run(
                    [sys.executable, "-c", WORKER, str(root), tmp, program, name],
                    capture_output=True, text=True, timeout=MUTANT_TIMEOUT, env=env, cwd=root,
                )
                # a mutant that crashes on import or while replaying (-1) changed the behavior: caught
                failing = int(proc.stdout.strip().splitlines()[-1]) if proc.returncode == 0 and proc.stdout.strip() else -1
                change = _describe(site)
            except subprocess.TimeoutExpired:
                failing, change = -1, _describe(site) + " (it made the program hang)"
            return Mutant(site.line, _cobol_line(src_lines, site.line), change, failing != 0, max(failing, 0), site.kind, site.before, site.after)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(one, enumerate(sites)))
    caught = sum(m.caught for m in results)
    mutants = [m.__dict__ for m in results]
    from .gapfill import annotate  # remembered verdicts from the gap filler (imported here: it imports this module)

    equivalent = annotate(program, source, mutants, root)
    return {
        "program": program,
        "implementation": implementation,
        "records": sum(v["records"] for v in baseline),
        "total": len(results),
        "caught": caught,
        "equivalent": equivalent,
        "mutants": mutants,
    }

