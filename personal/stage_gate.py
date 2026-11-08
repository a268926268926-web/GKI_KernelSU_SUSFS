#!/usr/bin/env python3
"""Require a same-commit predecessor, with one pinned, tested C2 reuse for C3."""
import json
import os
from pathlib import Path
import re
import subprocess

REPOSITORY = "a268926268926-web/GKI_KernelSU_SUSFS"
WORKFLOW_PATH = ".github/workflows/personal-oneplus15.yml"
TESTED_C2_RUN = 42499401579
TESTED_C2_SHA = "ae5dd5c162eba768de86aafda75c6b166c6dcc98"
PRIOR_STAGE = {"C2": "C1", "C2D1": "C1", "C2D2": "C1", "C3": "C2", "C": "C3"}
# This exception covers the approved daily network policy and C3 integration
# repair only. Source locks, manifests, patches and actions cannot be reused.
ALLOWED_C3_PATHS = frozenset({
    "personal/configure.py", "personal/evidence.py", "personal/README.md",
    "personal/apply_rekernel.py", "personal/check.py", "personal/stage_gate.py",
    WORKFLOW_PATH,
})
WORKSPACE = Path(__file__).resolve().parent.parent


def validate_run(run, title, head_sha, run_id=None):
    expected = {"display_title": title, "head_sha": head_sha,
                "status": "completed", "conclusion": "success", "path": WORKFLOW_PATH}
    if run_id is not None:
        expected["id"] = run_id
    for key, value in expected.items():
        if run.get(key) != value:
            raise ValueError(f"Predecessor run {key} mismatch: {run.get(key)!r}")
    if run.get("repository", {}).get("full_name") != REPOSITORY:
        raise ValueError("Predecessor run repository mismatch")
    return {key: run[key] for key in ["id", "display_title", "head_sha", "status", "conclusion", "path"]} | {
        "repository": REPOSITORY}


def same_head_predecessor(variant, head_sha, runs):
    title = f"OnePlus 15 {PRIOR_STAGE[variant]}"
    for run in runs:
        if run.get("display_title") == title:
            # A matching title must also have the exact head, status and source.
            return validate_run(run, title, head_sha)
    return None


def require_reusable_c2(variant, run, paths):
    if variant != "C3":
        raise ValueError(f"{variant} requires a successful predecessor at the same HEAD")
    record = validate_run(run, "OnePlus 15 C2", TESTED_C2_SHA, TESTED_C2_RUN)
    unexpected = set(paths) - ALLOWED_C3_PATHS
    if unexpected:
        raise ValueError(f"Tested C2 cannot cover changed paths: {sorted(unexpected)}")
    return record


def source_delta(head_sha, include_worktree=False):
    # No fetch or inferred merge base: the full checkout must contain this
    # exact tested source commit as an ancestor of the requested candidate.
    subprocess.run(["git", "merge-base", "--is-ancestor", TESTED_C2_SHA, head_sha],
                   cwd=WORKSPACE, check=True)
    args = ["git", "diff", "--name-only", "--no-renames", "-z", TESTED_C2_SHA]
    if not include_worktree:
        args.append(head_sha)
    raw = subprocess.check_output(args + ["--"], cwd=WORKSPACE)
    paths = set(raw.decode().rstrip("\0").split("\0")) if raw else set()
    if include_worktree:
        untracked = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "personal", ".github"],
            cwd=WORKSPACE)
        paths.update(untracked.decode().rstrip("\0").split("\0") if untracked else [])
    return sorted(paths)


def github_json(endpoint):
    # API or decoding failures are fatal; never convert them to "no prior run".
    return json.loads(subprocess.check_output(["gh", "api", endpoint], text=True))


def run_gate(variant, head_sha, receipt=None):
    if receipt is None:
        receipt = {}
    if variant not in PRIOR_STAGE:
        raise ValueError(f"Unsupported gated variant: {variant}")
    if not re.fullmatch(r"[a-f0-9]{40}", head_sha):
        raise ValueError("Invalid candidate commit")
    if os.environ["GITHUB_REPOSITORY"] != REPOSITORY:
        raise ValueError("Candidate repository mismatch")
    actual_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    if actual_head != head_sha:
        raise ValueError("Checkout differs from the requested candidate commit")
    endpoint = f"repos/{REPOSITORY}/actions/workflows/personal-oneplus15.yml/runs"
    page = 1
    while True:
        response = github_json(f"{endpoint}?head_sha={head_sha}&status=success&per_page=100&page={page}")
        runs = response["workflow_runs"]
        prior = same_head_predecessor(variant, head_sha, runs)
        if prior is not None:
            return {"mode": "same-head", "prior_run": prior, "changed_paths": []}
        if len(runs) < 100:
            break
        page += 1
    if variant != "C3":
        raise ValueError(f"No successful same-HEAD {PRIOR_STAGE[variant]} run for {variant}")
    baseline = github_json(f"repos/{REPOSITORY}/actions/runs/{TESTED_C2_RUN}")
    receipt.update({"mode": "tested-c2-baseline", "baseline_commit": TESTED_C2_SHA,
                    "baseline_run_requested": TESTED_C2_RUN})
    receipt["prior_run"] = validate_run(baseline, "OnePlus 15 C2", TESTED_C2_SHA, TESTED_C2_RUN)
    paths = source_delta(head_sha)
    receipt.update({"changed_paths": paths, "allowed_changed_paths": sorted(ALLOWED_C3_PATHS)})
    prior = require_reusable_c2(variant, baseline, paths)
    return {"mode": "tested-c2-baseline", "prior_run": prior,
            "baseline_commit": TESTED_C2_SHA, "changed_paths": paths,
            "allowed_changed_paths": sorted(ALLOWED_C3_PATHS)}


def main():
    receipt = {"variant": os.environ.get("BUILD_VARIANT"),
               "candidate_commit": os.environ.get("GITHUB_SHA"), "repository": REPOSITORY}
    destination = WORKSPACE / "evidence/stage-gate.json"
    destination.parent.mkdir(exist_ok=True)
    try:
        receipt.update(run_gate(receipt["variant"], receipt["candidate_commit"], receipt))
        receipt["decision"] = "accepted"
    except Exception as error:
        receipt.update({"decision": "rejected", "error": str(error)})
        raise
    finally:
        destination.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"PASS: {receipt['variant']} stage gate ({receipt['mode']}); receipt: {destination}")


if __name__ == "__main__":
    main()
