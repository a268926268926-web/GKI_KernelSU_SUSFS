#!/usr/bin/env python3
"""Require all synced repositories to match the committed project locks."""
from pathlib import Path
import json
import re
import subprocess
import xml.etree.ElementTree as ET

workspace = Path(__file__).resolve().parent.parent
def projects(path):
    return {p.get("path", p.get("name")): p.get("revision") for p in ET.parse(path).findall("project")}
expected = projects(workspace / "personal/manifest.xml")
actual = projects(workspace / "evidence/resolved-manifest.xml")
assert actual == expected, "Resolved manifest drift"
locks = json.loads((workspace / "personal/locks.json").read_text())
assert len(expected) == locks["source_project_count"]
assert expected["common"] == locks["common"]
for path, commit in expected.items():
    head = subprocess.check_output(["git", "-C", str(workspace / "kernel" / path), "rev-parse", "HEAD"], text=True).strip()
    assert head == commit, (path, head, commit)
common = workspace / "kernel/common"
make = (common / "Makefile").read_text()
version = ".".join(re.search(rf"(?m)^{key}\s*=\s*(\d+)\s*$", make).group(1)
                   for key in ["VERSION", "PATCHLEVEL", "SUBLEVEL"])
assert version == locks["version"], (version, locks["version"])
constants = (common / "build.config.constants").read_text()
for key, value in locks["build_constants"].items():
    assert re.search(rf"(?m)^{re.escape(key)}={re.escape(str(value))}$", constants), (key, value)
snapshot = {"version": version, "common": locks["common"],
            "manifest": locks["manifest"], "superproject": locks["superproject"],
            "project_count": len(expected), "build_constants": locks["build_constants"]}
(workspace / "evidence/source-snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
print(f"PASS: all {len(expected)} source checkouts, Linux {version} and KMI constants match locks")
