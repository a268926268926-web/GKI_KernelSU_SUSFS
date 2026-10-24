#!/usr/bin/env python3
"""Require all synced repositories to match the committed project locks."""
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

workspace = Path(__file__).resolve().parent.parent
def projects(path):
    return {p.get("path", p.get("name")): p.get("revision") for p in ET.parse(path).findall("project")}
expected = projects(workspace / "personal/manifest.xml")
actual = projects(workspace / "evidence/resolved-manifest.xml")
assert actual == expected, "Resolved manifest drift"
for path, commit in expected.items():
    head = subprocess.check_output(["git", "-C", str(workspace / "kernel" / path), "rev-parse", "HEAD"], text=True).strip()
    assert head == commit, (path, head, commit)
print(f"PASS: all {len(expected)} source checkouts match locks")
