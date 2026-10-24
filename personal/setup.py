#!/usr/bin/env python3
"""Fetch locked components and integrate the selected native implementations."""
import json
import os
from pathlib import Path
import shutil
import subprocess

here = Path(__file__).resolve().parent
workspace = here.parent
locks = json.loads((here / "locks.json").read_text())
kernel = workspace / "kernel"
common = kernel / "common"
destinations = {"BakaSU": kernel / "BakaSU", "Baseband-guard": kernel / "Baseband-guard", "NoMount": common / "NoMount"}
def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)
def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()
for name, item in locks["components"].items():
    if name == "Droidspaces-OSS":
        # Its existing composite action clones and verifies this exact pin.
        continue
    dest = destinations.get(name, workspace / name)
    assert not dest.exists(), f"Refusing to overwrite {dest}"
    # BakaSU computes its driver version from history. Other components need
    # only their immutable tree. Fetch no unselected branch checkouts.
    run("git", "clone", "--no-checkout", "--filter=blob:none", item["url"], str(dest))
    run("git", "fetch", "--depth=1" if name != "BakaSU" else "--no-tags", "origin", item["commit"], cwd=dest)
    run("git", "checkout", "--detach", item["commit"], cwd=dest)
    assert git(dest, "rev-parse", "HEAD") == item["commit"]
    print(f"LOCKED {name} {item['commit']}", flush=True)

root = kernel / "BakaSU/kernel"
link = common / "drivers/kernelsu"
assert not link.exists() and not link.is_symlink()
link.symlink_to(os.path.relpath(root, link.parent))
for file, line in [("Makefile", "obj-$(CONFIG_KSU) += kernelsu/"), ("Kconfig", 'source "drivers/kernelsu/Kconfig"')]:
    path = common / "drivers" / file
    source = path.read_text()
    assert line not in source
    path.write_text(source + "\n" + line + "\n")

# Kleaf copies the symlinked sources without their parent .git metadata.
# Resolve source-dependent make helpers against the locked checkout, keeping
# upstream's real guard, hook checks, and code generators intact.
kbuild = root / "Kbuild"
source = kbuild.read_text()
anchor = "KSU_SRC := $(realpath $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))"
assert source.count(anchor) == 1
source = source.replace(anchor, f"KSU_SRC := {root}", 1)
# Exact two-line upstream fix d5e9e025: do not run generators when KSU is
# unset during clean/initial configuration. Keep candidate API/behavior pinned.
generator = "include $(KSU_SRC)/tools/code_generation/code_generation.mk"
assert source.count(generator) == 1
source = source.replace(generator, "ifneq ($(CONFIG_KSU),)\n" + generator + "\nendif", 1)
kbuild.write_text(source)

run("bash", str(kernel / "Baseband-guard/setup.sh"), locks["components"]["Baseband-guard"]["commit"], cwd=kernel)
assert git(kernel / "Baseband-guard", "rev-parse", "HEAD") == locks["components"]["Baseband-guard"]["commit"]
run("sh", str(common / "NoMount/kernel/setup.sh"), locks["components"]["NoMount"]["commit"], cwd=common)
assert git(common / "NoMount", "rev-parse", "HEAD") == locks["components"]["NoMount"]["commit"]
susfs = workspace / "susfs4ksu/kernel_patches"
for rel in ["fs", "include/linux"]:
    for source in (susfs / rel).iterdir():
        if source.is_file():
            shutil.copy2(source, common / rel / source.name)
run("python3", str(here / "prepare_susfs.py"), str(common), str(kernel / "BakaSU"), str(workspace / "susfs4ksu"))

with open(os.environ["GITHUB_ENV"], "a") as env:
    for key, value in {"ROOT_IMPLEMENTATION": "bakasu", "ROOT_COMMIT": locks["components"]["BakaSU"]["commit"], "SUSFS_COMMIT": locks["components"]["susfs4ksu"]["commit"]}.items():
        env.write(f"{key}={value}\n")
