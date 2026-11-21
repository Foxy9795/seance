"""Start Séance's MCP server from any Python, on any operating system, from any folder.

    python scripts/seance_mcp.py            stdio, for Kiro and every other MCP client
    python scripts/seance_mcp.py --http     streamable HTTP at http://127.0.0.1:8765/mcp (--port to change it)

MCP settings can then name this file instead of a path that only exists on one machine. It finds the virtual environment
next to it (.venv/Scripts/python.exe on Windows, .venv/bin/python elsewhere) and starts the server with it. Without one it
uses the Python that runs it, if that Python has the packages the server needs, and otherwise says how to set up.

Standard library only, so any Python 3 can run it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = (".venv/Scripts/python.exe", ".venv/bin/python", ".venv/bin/python3", "venv/Scripts/python.exe", "venv/bin/python")
SETUP = ("Séance's MCP server could not start: there is no virtual environment in {root}.\n"
         "Set it up once, then reconnect the server:\n"
         "  Windows:      .\\scripts\\setup.ps1\n"
         "  macOS, Linux: python3 -m venv .venv && .venv/bin/pip install -e .\n")


def venv_python(root: Path = ROOT) -> Path | None:
    for rel in CANDIDATES:
        p = root / rel
        if p.is_file():
            return p
    return None


def _has_packages() -> bool:
    try:
        import mcp  # noqa: F401
        import fastapi  # noqa: F401
        import hypothesis  # noqa: F401
    except ImportError:
        return False
    return True


def main(argv: list[str]) -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    target = venv_python()
    if target is None:
        if not _has_packages():
            sys.stderr.write(SETUP.format(root=ROOT))
            return 1
        target = Path(sys.executable)
    command = [str(target), "-m", "seance.mcp_server", *argv]
    if os.name != "nt":
        os.chdir(ROOT)
        os.execve(str(target), command, env)  # becomes the server: same process, same stdin and stdout
    # Windows has no exec: the child inherits this process's stdin and stdout and talks to the MCP client directly
    return subprocess.call(command, cwd=str(ROOT), env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
