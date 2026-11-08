#!/usr/bin/env python3
"""Resolve component version metadata before Kleaf and exclude nested Git data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


NOMOUNT_GIT_BLOCK = r'''NOMOUNT_COMMITS := $(shell \
    d='$(NM_REAL_PATH)'; \
    while [ -n "$$d" ] && [ "$$d" != "/" ] && [ ! -d "$$d/.git" ]; do d=$$(dirname "$$d"); done; \
    if [ -d "$$d/.git" ] && git -C "$$d" remote get-url origin 2>/dev/null | grep -q 'nomount'; then \
        git -C "$$d" rev-list --count HEAD 2>/dev/null; \
    fi)'''

BBG_GIT_BLOCK = r'''GIT_BIN := /usr/bin/env PATH="$$PATH":/usr/bin:/usr/local/bin git

ifeq ($(findstring $(srctree),$(src)),$(srctree))
  BBG_DIR := $(src)
else
  BBG_DIR := $(srctree)/$(src)
endif

$(shell cd $(BBG_DIR) && test -f .git/shallow && $(GIT_BIN) fetch --unshallow)

REPO_LINK := $(shell cd $(BBG_DIR) && $(GIT_BIN) remote get-url origin 2>/dev/null)
COMMIT_SHA := $(shell cd $(BBG_DIR) && $(GIT_BIN) rev-parse --short=8 HEAD 2>/dev/null)

ifeq ($(strip $(REPO_LINK)),)
  REPO_LINK := unknown
endif
ifeq ($(strip $(COMMIT_SHA)),)
  COMMIT_SHA := unknown
endif'''


def replace_block(source, original, replacement, label):
    """Allow the pinned upstream block or this script's exact resolved block."""
    if source.count(original) == 1 and replacement not in source:
        return source.replace(original, replacement, 1)
    if original not in source and source.count(replacement) == 1:
        return source
    raise ValueError(f"Unknown or duplicate {label} layout")


def stabilize_common_sources(source):
    """Change only common_kernel_sources' glob, preserving other exclusions."""
    anchor = 'filegroup(\n    name = "common_kernel_sources",\n'
    if source.count(anchor) != 1:
        raise ValueError("Unknown common_kernel_sources filegroup")
    start = source.index(anchor)
    end = source.find("\n)\n", start)
    if end < 0:
        raise ValueError("Unterminated common_kernel_sources filegroup")
    end += len("\n)\n")
    block = source[start:end]
    glob = '    srcs = glob(\n        ["**"],\n        exclude = [\n'
    if block.count(glob) != 1:
        raise ValueError("Unknown common_kernel_sources glob")
    original = '            ".git/**",\n'
    replacement = original + '            "**/.git/**",\n            "**/.git",\n'
    nested = ['            "**/.git/**",\n', '            "**/.git",\n']
    if block.count(original) != 1:
        raise ValueError("Unknown root Git exclusion")
    if block.count(replacement) == 1 and all(block.count(line) == 1 for line in nested):
        return source
    if any(line in block for line in nested):
        raise ValueError("Partial or duplicate nested Git exclusions")
    block = block.replace(original, replacement, 1)
    return source[:start] + block + source[end:]


def stabilize_nomount(source, commit_count):
    """Keep NoMount's flags and compatibility checks; resolve only its count."""
    if not isinstance(commit_count, int) or isinstance(commit_count, bool) or commit_count <= 0:
        raise ValueError("NoMount commit count must be a positive integer")
    resolved = (
        "# Resolved from the locked checkout before the Kleaf sandbox.\n"
        f"NOMOUNT_COMMITS := {commit_count}"
    )
    return replace_block(source, NOMOUNT_GIT_BLOCK, resolved, "NoMount metadata")


def repository_url(url):
    """Accept a literal HTTPS repository URL that is safe in a Make variable."""
    if not isinstance(url, str) or not re.fullmatch(r"https://[A-Za-z0-9.-]+/[A-Za-z0-9._/-]+", url):
        raise ValueError("Expected a literal HTTPS repository URL")
    return url.removesuffix(".git")


def stabilize_baseband_guard(source, commit, url):
    """Replace build-time Git discovery/fetch with the selected lock values."""
    if not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Expected a full Baseband-guard commit")
    resolved = (
        "# Resolved from personal/locks.json before the Kleaf sandbox.\n"
        f"REPO_LINK := {repository_url(url)}\n"
        f"COMMIT_SHA := {commit[:8]}"
    )
    return replace_block(source, BBG_GIT_BLOCK, resolved, "Baseband-guard metadata")


def git(path, *args):
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(path), *args], text=True
    ).strip()


def component_record(path, lock):
    """Verify the component owns its Git root rather than inheriting a parent."""
    commit = lock["commit"]
    if not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError(f"Invalid component commit for {path.name}")
    if not (path / ".git").exists() or Path(git(path, "rev-parse", "--show-toplevel")).resolve() != path.resolve():
        raise ValueError(f"Component is not its own checkout: {path}")
    head = git(path, "rev-parse", "HEAD")
    if head != commit:
        raise ValueError(f"Component HEAD differs from lock: {path.name}")
    count = git(path, "rev-list", "--count", "HEAD")
    if not count.isdecimal() or int(count) <= 0:
        raise ValueError(f"Invalid commit count for {path.name}")
    shallow = git(path, "rev-parse", "--is-shallow-repository")
    if shallow not in {"true", "false"}:
        raise ValueError(f"Unknown history state for {path.name}")
    return {"head": head, "commit_count": int(count), "history_shallow": shallow == "true",
            "repository": repository_url(lock["url"])}


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def prepare(workspace):
    """Validate every lock and source anchor before returning any file changes."""
    workspace = Path(workspace).resolve()
    lock_path = workspace / "personal/locks.json"
    lock_bytes = lock_path.read_bytes()
    locks = json.loads(lock_bytes)
    common = workspace / "kernel/common"
    nomount = common / "NoMount"
    baseband = workspace / "kernel/Baseband-guard"
    records = {name: component_record(path, locks["components"][name])
               for name, path in [("NoMount", nomount), ("Baseband-guard", baseband)]}
    if (common / "security/baseband-guard").resolve() != baseband.resolve():
        raise ValueError("Baseband-guard integration does not resolve to the locked checkout")
    if (common / "fs/nomount").resolve() != (nomount / "kernel/src").resolve():
        raise ValueError("NoMount integration does not resolve to the locked checkout")
    transformations = [
        (common / "BUILD.bazel", stabilize_common_sources),
        (nomount / "kernel/src/Makefile",
         lambda text: stabilize_nomount(text, records["NoMount"]["commit_count"])),
        (baseband / "Makefile", lambda text: stabilize_baseband_guard(
            text, records["Baseband-guard"]["head"], locks["components"]["Baseband-guard"]["url"])),
    ]
    changes = {}
    hashes = {}
    for path, transform in transformations:
        before = path.read_text()
        after = transform(before)
        changes[path] = after
        hashes[str(path.relative_to(workspace))] = {
            "before_sha256": sha256(before), "after_sha256": sha256(after)}
    record = {"components": records, "files": hashes,
              "locks_sha256": hashlib.sha256(lock_bytes).hexdigest(),
              "git_exclusions": ["**/.git/**", "**/.git"],
              "commit_count_scope": "Resolved checkout history; shallow history is recorded, not expanded."}
    return changes, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    changes, record = prepare(args.workspace)
    # No writes, including evidence-directory creation, precede full validation.
    for path, source in changes.items():
        if path.read_text() != source:
            path.write_text(source)
    evidence = args.workspace.resolve() / "evidence"
    evidence.mkdir(exist_ok=True)
    (evidence / "stable-inputs.json").write_text(json.dumps(record, indent=2) + "\n")
    print("PASS: nested Git data excluded; locked component metadata resolved before compilation")


if __name__ == "__main__":
    main()
