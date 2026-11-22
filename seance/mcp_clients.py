"""Séance's MCP server in every MCP client: the settings for Kiro, VS Code, Cursor, Claude Code, Claude Desktop, Windsurf,
Gemini CLI, Antigravity and Codex, in three forms.

  local     full paths on this machine: always works here, and only here
  portable  no machine-specific path; for a settings file committed with the repository, in clients that start the
            server in the project folder or expand ${workspaceFolder}. Needs `python` on PATH and the .venv from setup.
  http      a URL, no paths at all: http://127.0.0.1:8000/mcp while `seance serve` runs

Séance writes only files inside this folder (`--write`); for clients whose settings live in your home folder it prints
the settings and says where they go.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .recorder import ROOT

LAUNCHER = "scripts/seance_mcp.py"
APP_URL = "http://127.0.0.1:8000/mcp"
# tools that only read, or run the original program on input you give: safe to run without asking each time
READ_ONLY = ["list_programs", "list_samples", "extract_business_rules", "assess_workspace", "describe_program", "describe_layout",
             "run_legacy_program", "where_used"]
MODES = ("local", "portable", "http")


@dataclass(frozen=True)
class Client:
    key: str
    name: str
    project_file: str | None  # a settings file inside the project, which Séance may write
    user_file: str | None  # a settings file in the home folder, which Séance only prints
    servers_key: str = "mcpServers"
    http_key: str = "url"
    portable: str = "relative"  # how a portable entry names the launcher: relative, workspace (${workspaceFolder}) or none
    note: str = ""


def _claude_desktop_file() -> str:
    if sys.platform == "win32":
        return "%APPDATA%\\Claude\\claude_desktop_config.json"
    if sys.platform == "darwin":
        return "~/Library/Application Support/Claude/claude_desktop_config.json"
    return "~/.config/Claude/claude_desktop_config.json"


CLIENTS: dict[str, Client] = {c.key: c for c in (
    Client("kiro", "Kiro", ".kiro/settings/mcp.json", "~/.kiro/settings/mcp.json",
           note="Kiro starts workspace servers in the workspace folder and reloads the file when it is saved."),
    Client("vscode", "VS Code (GitHub Copilot)", ".vscode/mcp.json", None, servers_key="servers", portable="workspace"),
    Client("cursor", "Cursor", ".cursor/mcp.json", "~/.cursor/mcp.json", portable="workspace"),
    Client("claude-code", "Claude Code", ".mcp.json", None,
           note="Or run: claude mcp add --transport http seance " + APP_URL),
    Client("claude-desktop", "Claude Desktop", None, _claude_desktop_file(), portable="none", note="Restart Claude Desktop after editing."),
    Client("windsurf", "Windsurf", None, "~/.codeium/windsurf/mcp_config.json", http_key="serverUrl", portable="none"),
    Client("gemini", "Gemini CLI", ".gemini/settings.json", "~/.gemini/settings.json", http_key="httpUrl"),
    Client("antigravity", "Antigravity", None, "~/.gemini/antigravity/mcp_config.json", http_key="serverUrl", portable="none",
           note="In Antigravity: the agent panel's ... menu, MCP Servers, Manage MCP Servers, View raw config. Newer versions keep "
                "the file at ~/.gemini/config/mcp_config.json."),
    Client("codex", "OpenAI Codex", None, "~/.codex/config.toml", servers_key="mcp_servers", portable="none"),
)}


def venv_python(root: Path = ROOT) -> Path:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        if (root / rel).is_file():
            return root / rel
    return Path(sys.executable)


def entry(client: Client, mode: str, root: Path = ROOT) -> dict:
    """The server entry for one client, without the name it is filed under."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    if mode == "http":
        e: dict = {client.http_key: APP_URL}
        if client.key in ("vscode", "claude-code"):
            e = {"type": "http", "url": APP_URL}
    elif mode == "portable" and client.portable != "none":
        launcher = "${workspaceFolder}/" + LAUNCHER if client.portable == "workspace" else LAUNCHER
        e = {"command": "python", "args": [launcher]}
        if client.key == "vscode":
            e = {"type": "stdio", **e}
    else:
        e = {"command": str(venv_python(root)), "args": ["-m", "seance.mcp_server"], "env": {"PYTHONPATH": str(root)}}
        if client.key == "vscode":
            e = {"type": "stdio", **e}
    if client.key == "kiro":
        e.update({"disabled": False, "autoApprove": list(READ_ONLY)})
    return e


def merged(client: Client, mode: str, existing: dict | None, root: Path = ROOT) -> dict:
    """The whole settings file with Séance's entry put in. Other servers and settings are kept, and so is a list of
    approved tools the person made themselves."""
    cfg = json.loads(json.dumps(existing or {}))
    servers = cfg.setdefault(client.servers_key, {})
    new = entry(client, mode, root)
    old = servers.get("seance") or {}
    if "autoApprove" in old and "autoApprove" in new:
        new["autoApprove"] = old["autoApprove"]
    for k in ("disabledTools", "timeout"):
        if k in old:
            new[k] = old[k]
    servers["seance"] = new
    return cfg


def render(client: Client, mode: str, root: Path = ROOT) -> str:
    """What to paste into the client's settings."""
    e = entry(client, mode, root)
    if client.key == "codex":
        if "command" not in e:
            return "# Codex: use the local form; it starts the server itself\n" + render(client, "local", root)
        lines = ["[mcp_servers.seance]", f"command = {json.dumps(e['command'])}", f"args = {json.dumps(e['args'])}"]
        if e.get("env"):
            lines.append("env = { " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in e["env"].items()) + " }")
        return "\n".join(lines)
    return json.dumps({client.servers_key: {"seance": e}}, indent=2)


def write(client: Client, mode: str, root: Path = ROOT) -> Path:
    """Write the project settings file of a client that has one. Raises ValueError for the others."""
    if not client.project_file:
        raise ValueError(f"{client.name} keeps its settings in {client.user_file}, outside this folder; Séance does not write there. "
                         "Paste the printed settings into that file instead.")
    path = root / client.project_file
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"{path} is not valid JSON, so it was left alone: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged(client, mode, existing, root), indent=2) + "\n", encoding="utf-8")
    return path


def describe(client: Client, mode: str, root: Path = ROOT) -> str:
    where = client.project_file or client.user_file
    if client.project_file and client.user_file:
        where = f"{client.project_file} (this project) or {client.user_file} (every project)"
    head = f"# {client.name}: {where}"
    if mode == "portable" and client.portable == "none":
        head += "\n# This client starts servers outside the project, so here is the local form instead."
    if client.note:
        head += f"\n# {client.note}"
    return head + "\n" + render(client, mode, root)


def main(argv: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="seance mcp-config", description="Settings that connect an MCP client to Séance's MCP server.")
    p.add_argument("--client", default="kiro", choices=[*CLIENTS, "all"], help="which client (default kiro; all prints every one)")
    p.add_argument("--mode", default="local", choices=MODES,
                   help="local: full paths on this machine (default); portable: no machine paths, for a committed file; http: a URL to the running app")
    p.add_argument("--write", action="store_true", help="write the client's settings file inside this folder (other settings are kept)")
    a = p.parse_args(argv)
    clients = list(CLIENTS.values()) if a.client == "all" else [CLIENTS[a.client]]
    if a.write:
        if a.client == "all":
            print("--write needs one --client", file=sys.stderr)
            return 2
        try:
            path = write(clients[0], a.mode, ROOT)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            print(describe(clients[0], a.mode, ROOT))
            return 1
        print(f"wrote {path.relative_to(ROOT).as_posix()} ({a.mode})")
        if a.mode == "http":
            print("It connects while the app runs: python -m seance serve")
        return 0
    print("\n\n".join(describe(c, a.mode, ROOT) for c in clients))
    if a.mode == "http":
        print("\n# The URL answers while the app runs: python -m seance serve", file=sys.stderr if a.client != "all" else sys.stdout)
    return 0



