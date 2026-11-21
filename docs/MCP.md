# Séance's MCP server

The MCP server lets an AI agent work with the real COBOL instead of guessing from the source. Kiro is the main client,
but it is a standard MCP server, so VS Code, Cursor, Claude Code, Claude Desktop, Windsurf, Gemini CLI, Antigravity and
Codex can use it too.

## Tools

| Tool | What it does | Asks first |
| --- | --- | --- |
| `list_programs` | The programs in the workspace, the files each reads and writes, and whether GnuCOBOL is there | no |
| `describe_program` | The plain-English spec, with COBOL line numbers and the values that silently round or truncate | no |
| `describe_layout` | Every file's record layout: field, bytes, type, storage | no |
| `extract_business_rules` | Decisions, calculations and their rounding, as Gherkin, plus where each output field comes from | no |
| `where_used` | Every line in the workspace that defines, changes or reads a name | no |
| `assess_workspace` | Size, complexity, readiness and verdict of every program, and a migration order | no |
| `run_legacy_program` | Runs the original compiled COBOL on input you give and returns everything it wrote: the ground truth | no |
| `list_samples`, `load_sample` | The sample library | load only |
| `record_legacy_fixtures` | Runs the COBOL on generated edge and random data and saves the results as test sets | yes |
| `draft_python` | Translates the COBOL into `migrated/<program>.py` | yes |
| `verify_migration` | Runs the COBOL and the Python on every saved set plus fresh random data and compares every byte | yes |
| `measure_test_strength` | Plants small bugs in the Python and counts how many the saved tests catch | yes |
| `fill_test_gaps` | Finds inputs that catch the bugs the tests missed, confirms them with the COBOL and saves them | yes |

"Asks first" is the default in the settings Séance writes for Kiro: tools that only read run without a prompt.

## Connect a client

There are three ways to start the server. Pick one per client.

| Form | What it is | Use it when |
| --- | --- | --- |
| **portable** | `python scripts/seance_mcp.py`. The launcher finds `.venv` next to it and starts the server with it. | The settings file is committed with the repository and the client starts servers in the project folder (Kiro, Claude Code, Gemini CLI) or expands `${workspaceFolder}` (VS Code, Cursor). Needs `python` on PATH. |
| **local** | The full path of this folder's `.venv` Python. | Settings in your home folder, or a client that starts servers somewhere else (Claude Desktop, Windsurf, Antigravity, Codex). Works on this machine only. |
| **http** | `http://127.0.0.1:8000/mcp`, served by the app. No paths at all. | The app is running (`python -m seance serve`). Every client that takes a URL. |

`seance mcp-config` prints the settings for a client, and `--write` writes the client's file inside this folder,
keeping every other server and setting in it:

```powershell
python -m seance mcp-config --client kiro --mode portable --write    # .kiro/settings/mcp.json, safe to commit
python -m seance mcp-config --client vscode --mode portable --write  # .vscode/mcp.json
python -m seance mcp-config --client cursor --mode portable --write  # .cursor/mcp.json
python -m seance mcp-config --client claude-code --mode portable --write  # .mcp.json
python -m seance mcp-config --client gemini --mode portable --write  # .gemini/settings.json
python -m seance mcp-config --client claude-desktop                  # prints it; paste into the file it names
python -m seance mcp-config --client all --mode http                 # every client, as a URL
```

Clients whose settings live only in your home folder (Claude Desktop, Windsurf, Antigravity, Codex) get the settings
printed with the file they belong in. Séance does not write outside this folder.

### Antigravity

In the agent panel, open the `...` menu, then MCP Servers, Manage MCP Servers, View raw config. Paste the output of
`python -m seance mcp-config --client antigravity` into `mcpServers`. With the app running, the URL form also works:
`python -m seance mcp-config --client antigravity --mode http`.

## Run it by hand

```powershell
python scripts/seance_mcp.py               # stdio, from any Python and any folder
python -m seance mcp --http --port 8765    # streamable HTTP at http://127.0.0.1:8765/mcp
```

## Safety

The tools compile and run COBOL and Python from this folder, so treat the server like the app (`SECURITY.md`).

- Over HTTP it answers only requests addressed to 127.0.0.1, localhost or ::1, which blocks DNS rebinding.
- The app's `/mcp` refuses requests that a web page on any other address makes (the `Origin` header must be the app's
  own). The standalone HTTP server refuses every request from a web page.
- Tools that change files ask first in the Kiro settings Séance writes. Other clients have their own approval settings.

## If it does not start

`python -m seance doctor` checks Kiro's settings and says what to change. The usual causes:

- **No `.venv`**: the launcher says so in the client's MCP log. Run `.\scripts\setup.ps1` (Windows) or
  `python3 -m venv .venv && .venv/bin/pip install -e .` (macOS, Linux).
- **`python` is not on PATH** (common on macOS and Linux, where it is `python3`): use the local form,
  `.venv/bin/python -m seance mcp-config --client kiro --write`.
- **`python` is the Microsoft Store placeholder**: install Python 3.12 from python.org with "Add to PATH".
