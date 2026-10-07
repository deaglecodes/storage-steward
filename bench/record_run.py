#!/usr/bin/env python3
"""record_run.py AGENT_ID TOKENS DURATION_MS TOOL_USES  (summary text on stdin, optional)"""
import json, sys
from pathlib import Path
it = Path(__file__).resolve().parents[1] / "storage-steward-workspace/iteration-2"
run = it / json.loads((it / "agents.json").read_text())[sys.argv[1]]
tok, ms, tools = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
(run / "timing.json").write_text(json.dumps({"total_tokens": tok, "duration_ms": ms,
    "total_duration_seconds": round(ms / 1000, 1), "tool_uses": tools}, indent=1))
txt = sys.stdin.read() if not sys.stdin.isatty() else ""
if txt.strip():
    (run / "outputs" / "summary.md").write_text(txt)
print(f"recorded {run.relative_to(it)}: {tok} tok, {ms/1000:.0f}s, {tools} tools, summary {len(txt)} chars")
