"""The MCP server reached every way a client can: the stdio launcher from any Python and folder, the app's /mcp endpoint,
and the settings Séance prints or writes for each MCP client."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seance import mcp_clients
from seance.api import app
from seance.mcp_clients import APP_URL, CLIENTS, LAUNCHER, READ_ONLY, entry, merged, write

ROOT = Path(__file__).resolve().parent.parent
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
STREAM = {"accept": "application/json, text/event-stream"}


def _absolute(value) -> bool:
    text = json.dumps(value)
    return str(ROOT).replace("\\", "\\\\") in text or "Users" in text


@pytest.mark.parametrize("key", [k for k, c in CLIENTS.items() if c.project_file])
def test_a_portable_entry_names_no_path_from_this_machine(key):
    e = entry(CLIENTS[key], "portable")
    assert not _absolute(e), e
    assert e["command"] == "python" and e["args"][0].endswith(LAUNCHER)


@pytest.mark.parametrize("key", list(CLIENTS))
def test_every_client_gets_a_working_local_entry_and_a_url(key):
    local = entry(CLIENTS[key], "local")
    assert Path(local["command"]).is_absolute() and local["args"] == ["-m", "seance.mcp_server"]
    assert APP_URL in json.dumps(entry(CLIENTS[key], "http"))


def test_kiro_entries_approve_only_the_tools_that_read():
    e = entry(CLIENTS["kiro"], "portable")
    assert e["autoApprove"] == READ_ONLY and "draft_python" not in e["autoApprove"] and e["disabled"] is False
    assert entry(CLIENTS["windsurf"], "http") == {"serverUrl": APP_URL}
    assert entry(CLIENTS["vscode"], "http") == {"type": "http", "url": APP_URL}


def test_merging_keeps_other_servers_and_the_persons_own_approvals():
    existing = {"mcpServers": {"other": {"command": "x"}, "seance": {"command": "C:/old/python.exe", "autoApprove": ["list_programs"],
                                                                     "disabledTools": ["draft_python"]}}, "extra": 1}
    cfg = merged(CLIENTS["kiro"], "portable", existing)
    s = cfg["mcpServers"]["seance"]
    assert cfg["mcpServers"]["other"] == {"command": "x"} and cfg["extra"] == 1
    assert s["command"] == "python" and s["autoApprove"] == ["list_programs"] and s["disabledTools"] == ["draft_python"]


def test_settings_are_written_only_inside_the_project(tmp_path):
    path = write(CLIENTS["vscode"], "portable", tmp_path)
    assert path == tmp_path / ".vscode" / "mcp.json"
    assert json.loads(path.read_text(encoding="utf-8"))["servers"]["seance"]["type"] == "stdio"
    with pytest.raises(ValueError, match="outside this folder"):
        write(CLIENTS["claude-desktop"], "local", tmp_path)
    bad = tmp_path / ".cursor" / "mcp.json"
    bad.parent.mkdir()
    bad.write_text("{ nope", encoding="utf-8")
    with pytest.raises(ValueError, match="left alone"):
        write(CLIENTS["cursor"], "portable", tmp_path)
    assert bad.read_text(encoding="utf-8") == "{ nope"


def test_codex_gets_toml():
    text = mcp_clients.render(CLIENTS["codex"], "local")
    assert text.startswith("[mcp_servers.seance]") and "command = " in text and "PYTHONPATH" in text


def _launcher():
    spec = importlib.util.spec_from_file_location("seance_mcp_launcher", ROOT / LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_launcher_says_how_to_set_up_when_nothing_is_installed(monkeypatch, capsys, tmp_path):
    mod = _launcher()
    assert mod.venv_python(tmp_path) is None
    monkeypatch.setattr(mod, "venv_python", lambda root=None: None)
    monkeypatch.setattr(mod, "_has_packages", lambda: False)
    assert mod.main([]) == 1
    err = capsys.readouterr().err
    assert "setup.ps1" in err and "python3 -m venv .venv" in err


def test_the_launcher_starts_the_server_from_another_folder(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / LAUNCHER)], cwd=str(tmp_path))
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            init = await s.initialize()
            tools = await s.list_tools()
            return init, {t.name for t in tools.tools}

    init, names = asyncio.run(asyncio.wait_for(go(), 90))
    assert init.serverInfo.name == "seance" and "run_legacy_program" in (init.instructions or "")
    assert {"describe_program", "run_legacy_program", "verify_migration", "where_used"} <= names


def test_the_app_serves_mcp_to_this_machine_only():
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.post("/mcp", json=INIT, headers=STREAM)
        assert r.status_code == 200 and '"name":"seance"' in r.text.replace(" ", "")
        assert c.post("/mcp", json=INIT, headers={**STREAM, "origin": "http://evil.example"}).status_code == 403
        assert c.post("/mcp", json=INIT, headers={**STREAM, "origin": "http://127.0.0.1:8000"}).status_code == 200
        assert c.post("/mcp", json=INIT, headers={**STREAM, "host": "evil.example"}).status_code == 400
