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
    if step.get("uses", "").startswith("./"):
        action = yaml.safe_load((workspace / step["uses"] / "action.yml").read_text())
        inputs = action.get("inputs", {})
        provided = step.get("with", {})
        assert set(provided) <= set(inputs), (step["name"], "unknown action inputs")
        for key, definition in inputs.items():
            if definition.get("required") and "default" not in definition:
                assert key in provided, (step["name"], "missing required input", key)
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
nft = locks["network_patches"]["nft_pernet"]
assert hashlib.sha256((here / "patches/network" / nft["path"]).read_bytes()).hexdigest() == nft["sha256"]
projects = ET.parse(here / "manifest.xml").findall("project")
assert len(projects) == locks["source_project_count"]
assert len({p.get("path", p.get("name")) for p in projects}) == len(projects)
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
assert locks["upstream_release"] == "r22"
assert locks["version"] == "6.12.96" and locks["patch_level"] == "lts"
assert locks["build_constants"]["KMI_GENERATION"] == "6"
assert locks["source_date_epoch"] == 0, "Non-stamped Kleaf builds use epoch zero"
assert isinstance(locks["source_commit_epoch"], int) and locks["source_commit_epoch"] > 0
assert locks["wild"] == "8d8e03391f26677b033d3c27face86a738a6a319"
subprocess.run(["git", "merge-base", "--is-ancestor", locks["wild"], "HEAD"], cwd=workspace, check=True)
assert locks["bakasu_codegen_guard_upstream"] == locks["components"]["BakaSU"]["commit"]
assert locks["manager"]["commit"] == locks["components"]["BakaSU"]["commit"]
assert locks["nomount_protocol"] == 22
assert not any("stock-config" in s.get("uses", "") for s in data["jobs"]["build"]["steps"])
assert any(s.get("name") == "Require successful A before B" and s.get("if") == "env.BUILD_VARIANT == 'B'" for s in data["jobs"]["build"]["steps"])
triggers = data.get("on", data.get(True))
variants = triggers["workflow_dispatch"]["inputs"]["variant"]["options"]
assert {"C1", "C2", "C2D1", "C2D2", "C3", "C"} <= set(variants)
assert any(s.get("name") == "Apply locked LZ4 source chain" for s in data["jobs"]["build"]["steps"])
assert any(s.get("name") == "Apply locked BBRv3 source backport" for s in data["jobs"]["build"]["steps"])
assert any(s.get("name") == "Preserve public network namespace layout for NFT" and
           s.get("run") == "python3 personal/apply_nft_compat.py" for s in data["jobs"]["build"]["steps"])
assert any(s.get("name") == "Apply locked Re:Kernel source integration" for s in data["jobs"]["build"]["steps"])
assert any(s.get("name") == "Require prior successful C stage" for s in data["jobs"]["build"]["steps"])
stage_step = next(s for s in data["jobs"]["build"]["steps"] if s.get("name") == "Require prior successful C stage")
assert "python3 personal/stage_gate.py" in stage_step["run"]
assert stage_step["if"] == "env.BUILD_VARIANT == 'C2' || env.BUILD_VARIANT == 'C2D1' || env.BUILD_VARIANT == 'C2D2' || env.BUILD_VARIANT == 'C3' || env.BUILD_VARIANT == 'C'"
stage_spec = importlib.util.spec_from_file_location("stage_gate", here / "stage_gate.py")
stage_gate = importlib.util.module_from_spec(stage_spec)
stage_spec.loader.exec_module(stage_gate)
# Fixed API metadata is a local contract fixture, not evidence of a live API
# call. The CI gate always queries GitHub before accepting this baseline.
tested_c2 = {
    "id": 42499401579, "display_title": "OnePlus 15 C2", "status": "completed",
    "conclusion": "success", "head_sha": "ae5dd5c162eba768de86aafda75c6b166c6dcc98",
    "repository": {"full_name": "a268926268926-web/GKI_KernelSU_SUSFS"},
    "path": ".github/workflows/personal-oneplus15.yml",
}
assert stage_gate.require_reusable_c2("C3", tested_c2, stage_gate.ALLOWED_C3_PATHS)["id"] == tested_c2["id"]

def rejects_stage_gate(operation):
    try:
        operation()
    except (ValueError, subprocess.CalledProcessError):
        return
    raise AssertionError("Invalid stage dependency was accepted")

for field, invalid in {
    "id": 42499401580, "display_title": "OnePlus 15 C2D2", "status": "in_progress",
    "conclusion": "failure", "head_sha": "0" * 40,
    "repository": {"full_name": "another-user/GKI_KernelSU_SUSFS"},
    "path": ".github/workflows/other.yml",
}.items():
    bad_run = copy.deepcopy(tested_c2)
    bad_run[field] = invalid
    rejects_stage_gate(lambda: stage_gate.require_reusable_c2("C3", bad_run, []))
for variant in ["C2", "C2D1", "C2D2", "C"]:
    rejects_stage_gate(lambda: stage_gate.require_reusable_c2(variant, tested_c2, []))
for path in ["personal/locks.json", "personal/manifest.xml", "personal/setup.py",
             "personal/patches/network/new.patch", ".github/actions/networking-config/action.yml",
             "personal/modules/module.c", "personal/lz4/lz4.c", "personal/adios/adios.c"]:
    rejects_stage_gate(lambda: stage_gate.require_reusable_c2("C3", tested_c2, [path]))
# Check real Git ancestry and all current committed/uncommitted recipe paths,
# including the new helper; a synthetic network mock cannot hide source drift.
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace, text=True).strip()
actual_delta = stage_gate.source_delta(head, include_worktree=True)
reuse_eligible = set(actual_delta) <= stage_gate.ALLOWED_C3_PATHS
if reuse_eligible:
    stage_gate.require_reusable_c2("C3", tested_c2, actual_delta)
else:
    # A later source/lock upgrade must reject reuse, while its normal same-HEAD
    # predecessor path remains available rather than failing every local check.
    rejects_stage_gate(lambda: stage_gate.require_reusable_c2("C3", tested_c2, actual_delta))
before_baseline = subprocess.check_output(
    ["git", "rev-parse", stage_gate.TESTED_C2_SHA + "^"], cwd=workspace, text=True).strip()
rejects_stage_gate(lambda: stage_gate.source_delta(before_baseline))
for variant, prior in stage_gate.PRIOR_STAGE.items():
    prior_run = copy.deepcopy(tested_c2)
    prior_run.update({"display_title": f"OnePlus 15 {prior}", "head_sha": head})
    assert stage_gate.same_head_predecessor(variant, head, [prior_run])["head_sha"] == head
    prior_run["head_sha"] = "0" * 40
    rejects_stage_gate(lambda: stage_gate.same_head_predecessor(variant, head, [prior_run]))
print(f"PASS: pinned C3 baseline gate, metadata/path rejection cases, real Git ancestry; {len(actual_delta)} changed paths, reuse_eligible={reuse_eligible}")
build_step = next(s for s in data["jobs"]["build"]["steps"] if s.get("id") == "compile")
assert "--config=fast" not in build_step["run"] and "--config=local" not in build_step["run"], "LOCAL KernelBuild cannot use the disk cache"
assert "--disk_cache=" in build_step["run"] and "--repository_cache=" in build_step["run"]
step_names = [s.get("name") for s in data["jobs"]["build"]["steps"]]
assert step_names.index("Assert version and final requested choices") < step_names.index("Stabilize component metadata and Bazel source inputs") < step_names.index("Archive source changes before compilation")
assert locks["components"]["Re-Kernel"]["commit"] == "ac08296174d7fb2801c0eee1084f067a34f8a0fe"
print(f"PASS: {shells} workflow shell blocks, local action inputs, Python syntax, {len(projects)} immutable project pins, R22/LTS96 source contracts, config failure gates, stage dependencies")
