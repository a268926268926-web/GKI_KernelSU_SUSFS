#!/usr/bin/env python3
"""Local syntax and failure-gate checks; no kernel build or device access."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

import yaml

here = Path(__file__).resolve().parent
workspace = here.parent
workflow = workspace / ".github/workflows/personal-oneplus15.yml"
data = yaml.safe_load(workflow.read_text())
for path in here.glob("*.py"):
    ast.parse(path.read_text(), filename=str(path))
shells = 0
for step in data["jobs"]["build"]["steps"]:
    if "run" in step:
        script = re.sub(r"\$\{\{.*?\}\}", "test-value", step["run"])
        subprocess.run(["bash", "-n"], input=script, text=True, check=True)
        shells += 1
locks = json.loads((here / "locks.json").read_text())
for file, expected in locks["lz4_patches"]["files"].items():
    patch = here / "patches/lz4" / file
    assert hashlib.file_digest(patch.open("rb"), "sha256").hexdigest() == expected
for file, expected in locks["lz4_backends"]["files"].items():
    backend = here / "lz4" / file
    assert hashlib.file_digest(backend.open("rb"), "sha256").hexdigest() == expected
bbr3 = here / "patches/network/0001-net-tcp-backport-BBRv3-to-android16-6.12.patch"
assert hashlib.file_digest(bbr3.open("rb"), "sha256").hexdigest() == locks["network_patches"]["bbrv3"]["sha256"]
projects = ET.parse(here / "manifest.xml").findall("project")
assert len(projects) == 50
assert all(re.fullmatch("[a-f0-9]{40}", p.get("revision", "")) for p in projects)
assert next(p for p in projects if p.get("path") == "common").get("revision") == locks["common"]
spec = importlib.util.spec_from_file_location("evidence", here / "evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)

# Missing final config/features must fail, rather than yield a candidate.
for config in [{}, {"CONFIG_ARM64_4K_PAGES": "y", "CONFIG_KSU": "y"},
               {"CONFIG_ARM64_16K_PAGES": "y", "CONFIG_KSU": "y", "CONFIG_KSU_SUSFS": "y"}]:
    try:
        evidence.require_config(config)
    except AssertionError:
        pass
    else:
        raise AssertionError("Incomplete configuration was accepted")
assert evidence.config_values('# CONFIG_KSU is not set\nCONFIG_DEFAULT_TCP_CONG="bbr"\n') == {
    "CONFIG_KSU": "n", "CONFIG_DEFAULT_TCP_CONG": '"bbr"'}
assert locks["allow_version_mismatch"] is False and locks["perf"] is False
assert any(s.get("name") == "Require successful A before B" and s.get("if") == "env.BUILD_VARIANT == 'B'" for s in data["jobs"]["build"]["steps"])
triggers = data.get("on", data.get(True))
variants = triggers["workflow_dispatch"]["inputs"]["variant"]["options"]
assert {"C1", "C2", "C2D1", "C2D2", "C3", "C"} <= set(variants)
assert any(s.get("name") == "Apply locked LZ4 source chain" for s in data["jobs"]["build"]["steps"])
assert any(s.get("name") == "Apply locked BBRv3 source backport" for s in data["jobs"]["build"]["steps"])
assert any(s.get("name") == "Apply locked Re:Kernel source integration" for s in data["jobs"]["build"]["steps"])
assert any(s.get("name") == "Require prior successful C stage" for s in data["jobs"]["build"]["steps"])
assert locks["components"]["Re-Kernel"]["commit"] == "ac08296174d7fb2801c0eee1084f067a34f8a0fe"
print(f"PASS: {shells} workflow shell blocks, Python syntax, 50 immutable project pins, config failure gates, B dependency")
