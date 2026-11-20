# Security

## What Séance does that matters for security

Séance compiles and runs the COBOL you give it, and runs Python it generates or that you write. Treat it like a local
development server: it is for code you trust, on your own machine.

- The app listens on `127.0.0.1` only, and answers only requests addressed to `127.0.0.1`, `localhost` or `::1`. That
  blocks DNS rebinding, where a web page tries to reach a local server through a name it controls.
- Every request that changes anything must be JSON and carry a random token created when the app starts. Only the page
  the app serves knows it, so another web site cannot drive the app from your browser.
- Programs run in a temporary folder with a time limit. They are not sandboxed beyond that: a program can read and
  write anything your user account can.
- Uploaded files and sources have size limits (200 KB of source, 5,000 records per data file).
- The page makes no requests to other hosts. Séance sends nothing anywhere and has no telemetry.
- `seance setup` downloads one file, the GnuCOBOL 3.1.2 build, from its GitHub release, and refuses it unless its
  SHA-256 matches the value fixed in `seance/toolchain.py`.
- The MCP server runs over standard input and output for Kiro only. Kiro asks before using a tool that writes files;
  only the read-only tools are approved in advance in `.kiro/settings/mcp.json`.

## Reporting a problem

Please report security problems privately to the maintainers rather than in a public issue, with the steps to reproduce
it and the output of `python -m seance doctor --json`. You will get an answer within a week.

## Supported versions

Only the latest release receives fixes.
