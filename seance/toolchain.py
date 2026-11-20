"""GnuCOBOL for Séance: find it, or download the pinned Windows build, check its SHA-256, and unpack it.

    python -m seance setup              GnuCOBOL into tools/gnucobol (Windows), or what to install elsewhere
    python -m seance setup --mcp-config write .kiro/settings/mcp.json for this folder

The build is the one the samples and tests were recorded with. Its checksum is fixed here, so a changed or
damaged download is refused before anything is unpacked. Nothing that is already installed is overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from .recorder import ROOT, cobc_path, cobol_env

RELEASE = "3.1.2-20230124"
FOLDER = "gnucobol-3.1.2-windows-mingw-x64"
ARCHIVE = f"{FOLDER}.7z"
URL = f"https://github.com/mridoni/gnucobol-binaries/releases/download/{RELEASE}/{ARCHIVE}"
SHA256 = "f06fdc6ebec1a7ecbab036e5fcfc5280fdfadef34af0e131b6f8a9bf13bccf5e"
SIZE = 86_205_348
ELSEWHERE = ("GnuCOBOL 3.1.2 is downloaded automatically on Windows only. On Linux install it with your package manager "
             "(Debian and Ubuntu: sudo apt install gnucobol3), on macOS with Homebrew (brew install gnucobol), then run "
             "python -m seance doctor.")


class ToolchainError(RuntimeError):
    pass


def cobc_version(path: str | None = None) -> str | None:
    """The first line of `cobc --version`, or None when there is no working cobc."""
    path = path or cobc_path()
    if not path:
        return None
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, env=cobol_env(), timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out.splitlines()[0].strip() if out.strip() else None


def download(url: str, dest: Path, sha256: str, size: int | None = None, say=print) -> Path:
    """Fetch url to dest unless a file with the right checksum is already there. A wrong checksum is an error and
    the partial file is removed."""
    if dest.exists() and _sha256(dest) == sha256:
        say(f"using the archive already downloaded: {dest}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h, done, shown = hashlib.sha256(), 0, -1
    try:
        with urllib.request.urlopen(url, timeout=60) as r, part.open("wb") as out:
            total = size or int(r.headers.get("Content-Length") or 0)
            say(f"downloading {url}" + (f" ({total / 1e6:.0f} MB)" if total else ""))
            while chunk := r.read(1 << 20):
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if total and done * 10 // total > shown:
                    shown = done * 10 // total
                    say(f"  {min(shown * 10, 100)}%")
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise ToolchainError(f"The download failed: {exc}. Check the network, or download {url} yourself and put it at {dest}.") from exc
    if h.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise ToolchainError(f"The downloaded file does not have the expected SHA-256 ({sha256[:16]}...). It was deleted and nothing was "
                             "unpacked. Try again; if it happens again, the file on the server has changed.")
    part.replace(dest)
    return dest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def unpack(archive: Path, target: Path, folder: str = FOLDER) -> Path:
    """Unpack archive (7z, zip or tar) so that target/folder holds its contents. The archive is unpacked into a
    staging folder first and moved into place only when it holds folder/bin, so a failed run leaves nothing behind."""
    final = target / folder
    if final.exists():
        raise ToolchainError(f"{final} already exists. Delete it yourself if you want it unpacked again.")
    stage = target / ".unpacking"
    if stage.exists():
        shutil.rmtree(stage)  # our own staging folder from a run that was interrupted
    stage.mkdir(parents=True)
    try:
        tools = [["tar", "-xf", str(archive), "-C", str(stage)]]
        if shutil.which("7z"):
            tools.append(["7z", "x", "-y", f"-o{stage}", str(archive)])
        errors = []
        for cmd in tools:
            if not shutil.which(cmd[0]):
                errors.append(f"{cmd[0]} is not installed")
                continue
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0 and (stage / folder / "bin").is_dir():
                break
            last = (proc.stderr or proc.stdout or "").strip().splitlines()
            errors.append(f"{cmd[0]}: {last[-1] if last else 'no output'}")
            for p in stage.iterdir():  # try the next tool on a clean folder
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        else:
            raise ToolchainError("The archive could not be unpacked (" + "; ".join(errors) + "). Unpack it yourself into " + str(target) + ".")
        (stage / folder).replace(final)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return final


def install(root: Path = ROOT, say=print, url: str = URL, sha256: str = SHA256) -> dict:
    """Make sure a cobc is available, downloading the pinned build on Windows when none is."""
    present = cobc_path()
    if present:
        return {"status": "present", "cobc": present, "version": cobc_version(present)}
    if os.name != "nt":
        raise ToolchainError(ELSEWHERE)
    target = root / "tools" / "gnucobol"
    if (target / FOLDER).exists():
        raise ToolchainError(f"{target / FOLDER} exists but holds no working cobc. Delete that folder and run this again.")
    archive = download(url, root / "build" / "downloads" / ARCHIVE, sha256, SIZE, say)
    say(f"unpacking into {target}")
    unpack(archive, target)
    found = cobc_path()
    version = cobc_version(found)
    if not version:
        raise ToolchainError(f"GnuCOBOL was unpacked into {target / FOLDER}, but cobc does not run. Run python -m seance doctor for details.")
    return {"status": "installed", "cobc": found, "version": version}


def mcp_config(root: Path = ROOT, existing: dict | None = None) -> dict:
    """The Kiro MCP settings for this folder: the seance server started with this folder's virtual environment.
    Other servers and settings in an existing file are kept as they are."""
    cfg = json.loads(json.dumps(existing or {}))
    servers = cfg.setdefault("mcpServers", {})
    venv_python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    entry = servers.setdefault("seance", {})
    entry["command"] = str(venv_python if venv_python.exists() else Path(sys.executable))
    entry["args"] = ["-m", "seance.mcp_server"]
    entry["env"] = {**entry.get("env", {}), "PYTHONPATH": str(root)}
    entry.setdefault("disabled", False)
    entry.setdefault("autoApprove", ["list_programs", "list_samples", "extract_business_rules", "assess_workspace",
                                     "describe_program", "describe_layout", "run_legacy_program", "where_used"])
    return cfg


def write_mcp_config(path: Path, root: Path = ROOT) -> dict:
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ToolchainError(f"{path} is not valid JSON, so it was left alone: {exc}") from exc
    cfg = mcp_config(root, existing)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg
