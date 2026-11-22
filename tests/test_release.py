"""Release tooling: packaging metadata, the GnuCOBOL download, the setup check."""
import hashlib
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seance import __version__
from seance.api import app
from seance.doctor import _satisfies, run
from seance.recorder import ROOT, cobc_available
from seance.toolchain import ToolchainError, download, mcp_config, unpack, write_mcp_config

needs_cobol = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL is not installed")


def _requirements() -> list[str]:
    return [line.strip() for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


def test_pyproject_and_requirements_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["dependencies"] == _requirements()
    assert project["requires-python"] == ">=3.12"
    assert "seance" in project["scripts"]


def test_the_changelog_names_this_version():
    top = re.search(r"^## \[?(\d+\.\d+\.\d+)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    assert top and top.group(1) == __version__


def test_version_flag():
    out = subprocess.run([sys.executable, "-m", "seance", "--version"], capture_output=True, text=True, cwd=ROOT, timeout=60).stdout
    assert out.strip() == f"seance {__version__}"


# ---- the download is checked before anything is unpacked

def _archive(tmp: Path, folder: str = "gc", with_bin: bool = True) -> Path:
    path = tmp / "gc.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{folder}/{'bin' if with_bin else 'lib'}/cobc.exe", b"not really cobc")
    return path


def test_a_download_with_the_right_checksum_is_kept(tmp_path):
    src = _archive(tmp_path)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    dest = download(src.as_uri(), tmp_path / "dl" / "gc.zip", sha, say=lambda *_: None)
    assert dest.read_bytes() == src.read_bytes()
    again = download("file:///does/not/exist", dest, sha, say=lambda *_: None)  # already there: not fetched again
    assert again == dest


def test_a_download_with_the_wrong_checksum_is_refused_and_removed(tmp_path):
    src = _archive(tmp_path)
    with pytest.raises(ToolchainError, match="SHA-256"):
        download(src.as_uri(), tmp_path / "dl" / "gc.zip", "0" * 64, say=lambda *_: None)
    assert not list((tmp_path / "dl").iterdir()), "nothing is left behind"


def test_unpacking_goes_through_a_staging_folder(tmp_path):
    target = tmp_path / "tools"
    final = unpack(_archive(tmp_path), target, "gc")
    assert (final / "bin" / "cobc.exe").exists() and not (target / ".unpacking").exists()
    with pytest.raises(ToolchainError, match="already exists"):
        unpack(_archive(tmp_path), target, "gc")


def test_an_archive_without_the_expected_folder_leaves_nothing(tmp_path):
    target = tmp_path / "tools"
    with pytest.raises(ToolchainError):
        unpack(_archive(tmp_path, with_bin=False), target, "gc")
    assert not (target / "gc").exists() and not (target / ".unpacking").exists()


# ---- Kiro's MCP settings for this folder

def test_mcp_settings_keep_what_else_is_there(tmp_path):
    existing = {"mcpServers": {"other": {"command": "x"}, "seance": {"command": "C:/elsewhere/python.exe", "autoApprove": ["list_programs"],
                                                                     "env": {"EXTRA": "1"}}}, "something": True}
    cfg = mcp_config(tmp_path, existing)
    s = cfg["mcpServers"]["seance"]
    assert cfg["mcpServers"]["other"] == {"command": "x"} and cfg["something"] is True
    assert s["args"] == ["-m", "seance.mcp_server"] and s["env"] == {"EXTRA": "1", "PYTHONPATH": str(tmp_path)}
    assert s["autoApprove"] == ["list_programs"], "the user's own approvals are kept"
    path = tmp_path / "mcp.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ToolchainError, match="not valid JSON"):
        write_mcp_config(path, tmp_path)
    assert path.read_text(encoding="utf-8") == "{ not json", "a file that cannot be read is left alone"


# ---- the setup check

def test_version_comparison():
    assert _satisfies("1.30.0", ">=1.9,<2") and not _satisfies("2.0.1", ">=1.9,<2") and not _satisfies("0.99", ">=0.115")
    assert _satisfies("0.164.0", ">=0.115") and _satisfies("9.2.0", ">=8")


@needs_cobol
def test_the_setup_check_passes_here():
    checks = {c.name: c for c in run()}
    assert not [c for c in checks.values() if c.level == "fail"], [c for c in checks.values() if c.level == "fail"]
    assert checks["Compile, run and compare"].level == "ok", checks["Compile, run and compare"]


@needs_cobol
def test_the_app_runs_the_setup_check():
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    assert c.post("/api/doctor").status_code == 403, "it compiles a program, so it needs the page's token"
    r = c.post("/api/doctor", json={}, headers={"x-seance-token": app.state.token})
    assert r.status_code == 200 and r.json()["ok"] is True

def test_bare_command_shows_an_overview():
    proc = subprocess.run([sys.executable, "-m", "seance"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=60, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc.returncode == 0 and "seance serve" in proc.stdout and "seance doctor" in proc.stdout


def test_an_installed_copy_without_its_folder_says_so(monkeypatch, tmp_path):
    from seance import cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    assert "pip install -e ." in cli._home_problem()
    assert cli.main(["doctor"]) == 2
