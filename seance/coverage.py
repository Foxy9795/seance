"""Which COBOL statements the saved test runs reach.

A translated program tags every line with the COBOL line it came from (# L42, or # PRICER L12 in a called
program). Replaying the saved runs under a line tracer tells which tagged lines ran, so the report can say
"the tests reach 94% of the COBOL statements; lines 61 and 88 are never reached". Unreached lines are where a
difference could hide, so they are listed as needing review. Hand-written Python has no tags, so it gets no score.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_TAG = re.compile(r"#\s*(?:([A-Z0-9][A-Z0-9-]*)\s+)?L(\d+)\b")


def tagged_lines(source: str) -> dict[int, tuple[str, int]]:
    """Python line number -> (program, COBOL line). The main program is ''."""
    out = {}
    for i, text in enumerate(source.splitlines(), start=1):
        if "#" not in text or text.lstrip().startswith(("#", '"""')):
            continue
        m = _TAG.search(text[text.index("#"):])
        if m:
            out[i] = (m.group(1) or "", int(m.group(2)))
    return out


class Tracer:
    def __init__(self, filename: str):
        self.filename = str(Path(filename).resolve()).lower()
        self.hits: set[int] = set()

    def __enter__(self):
        mon = getattr(sys, "monitoring", None)
        if mon is not None:  # Python 3.12+: each line reports once, then switches itself off, so this costs almost nothing
            self.tool = mon.COVERAGE_ID
            try:
                mon.use_tool_id(self.tool, "seance")
            except ValueError:
                self.tool = None
            if self.tool is not None:
                target = self.filename

                def on_line(code, line):
                    if str(Path(code.co_filename).resolve()).lower() == target:
                        self.hits.add(line)
                    return mon.DISABLE

                mon.register_callback(self.tool, mon.events.LINE, on_line)
                mon.set_events(self.tool, mon.events.LINE)
                mon.restart_events()
                return self
        self.tool = None
        self.prev = sys.gettrace()
        sys.settrace(self._global)
        return self

    def __exit__(self, *exc):
        if self.tool is not None:
            mon = sys.monitoring
            mon.set_events(self.tool, 0)
            mon.register_callback(self.tool, mon.events.LINE, None)
            mon.free_tool_id(self.tool)
            return
        sys.settrace(self.prev)

    def _global(self, frame, event, arg):
        if event == "call" and str(Path(frame.f_code.co_filename).resolve()).lower() == self.filename:
            return self._local
        return None

    def _local(self, frame, event, arg):
        if event == "line":
            self.hits.add(frame.f_lineno)
        return self._local


def summarize(source: str, hits: set[int]) -> dict | None:
    tags = tagged_lines(source)
    if not tags:
        return None
    every = sorted(set(tags.values()))
    reached = {tags[n] for n in hits if n in tags}
    missed = [t for t in every if t not in reached]
    return {
        "statements": len(every),
        "reached": len(every) - len(missed),
        "percent": round(100 * (len(every) - len(missed)) / len(every), 1) if every else 100.0,
        "missed": [{"program": p, "line": n} for p, n in missed],
    }
