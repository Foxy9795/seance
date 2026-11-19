"""The tests use the sample library as their programs: load it into the workspace before collection, remove it after.

Only samples this run added are removed, and their compiled programs under build/ are kept so the next run starts fast.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_added: list[str] = []


def pytest_configure(config):
    from seance.programs import ProgramError
    from seance.samples import install, installed, sample_names

    before = set(installed())
    for name in sample_names():
        try:
            install(name)
        except ProgramError as exc:  # a program of your own with a sample's name: leave it alone, its tests will say so
            print(f"conftest: {exc}")
    _added[:] = sorted(set(installed()) - before)


def pytest_unconfigure(config):
    from seance.programs import delete_program

    for name in _added:
        delete_program(name, keep_build=True)
