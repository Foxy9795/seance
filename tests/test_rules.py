"""The Kiroween submission rules and the project's steering rules, checked by scripts/check_rules.py."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_rules.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_rules", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_rule_is_broken():
    results = _load().run()
    failed = [f"{rule}: {msg}" for level, rule, msg in results if level == "FAIL"]
    assert not failed, "\n".join(failed)
    assert len(results) >= 20, "the checks themselves must not shrink away"
