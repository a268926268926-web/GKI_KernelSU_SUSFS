#!/usr/bin/env python3
"""Fetch exact locked files for a bounded SUSFS and optional C1 rehearsal."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

here = Path(__file__).resolve().parent
locks = json.loads((here / "locks.json").read_text())
p = argparse.ArgumentParser()
p.add_argument("scratch", type=Path)
p.add_argument("--components", type=Path, help="Directory containing locked BakaSU and susfs4ksu checkouts")
p.add_argument("--lz4", action="store_true", help="Also replay the pinned C1 LZ4/LZ4KD chain")
p.add_argument("--source-cache", type=Path, help="Pristine files with source-index.json recording the locked common SHA and Git blob IDs")
a = p.parse_args()
scratch = a.scratch.resolve()
components = (a.components or scratch).resolve()
susfs = components / "susfs4ksu"
stage = scratch / "rehearsal"
assert not stage.exists(), "Use a fresh rehearsal directory"
patch = (susfs / "kernel_patches/50_add_susfs_in_gki-android16-6.12.patch").read_text()
paths = set(re.findall(r"(?m)^--- a/(\S+)", patch))
if a.lz4:
    for patch_file in [here / "patches/lz4/001-lz4.patch", here / "patches/lz4/lz4kd.patch"]:
        paths.update(re.findall(r"(?m)^--- a/(\S+)", patch_file.read_text()))
    paths.add("drivers/block/zram/zcomp.h")
paths = sorted(paths)
cache_files = {}
if a.source_cache:
    cache_index = json.loads((a.source_cache / "source-index.json").read_text())
    assert cache_index["common"] == locks["common"], "Source cache common SHA differs from locks.json"
    cache_files = {item["path"]: item for item in cache_index["pristine_files"]}
    assert len(cache_files) == len(cache_index["pristine_files"]), "Duplicate cache paths"
    assert set(paths) <= cache_files.keys(), "Source cache is incomplete"


def fetch(path):
    assert not path.startswith("/") and ".." not in Path(path).parts
    url = f"https://android.googlesource.com/kernel/common/+/{locks['common']}/{path}?format=TEXT"
    if a.source_cache:
        expected = cache_files[path]
        data = (a.source_cache / path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected["sha256"], path
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        assert blob == expected["git_blob"], (path, blob, expected["git_blob"])
        target = stage / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {**expected, "channel": "verified-source-cache", "cache_channel": expected.get("channel")}
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = base64.b64decode(response.read())
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "url": url, "channel": "gitiles-base64"}
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2)
with ThreadPoolExecutor(max_workers=6) as pool:
    fetched = list(pool.map(fetch, paths))
print(f"Fetched {len(fetched)} exact-source files", flush=True)
(scratch / "rehearsal-source.json").write_text(json.dumps({
    "common": locks["common"], "version": locks["version"],
    "stages": ["susfs", "lz4"] if a.lz4 else ["susfs"],
    "pristine_files": fetched,
}, indent=2) + "\n")
subprocess.run([sys.executable, str(here / "prepare_susfs.py"), str(stage), str(components / "BakaSU"), str(susfs)], check=True)
assert not list(stage.rglob("*.rej"))
print("PASS: complete SUSFS patch replay, zero rejects, fuzz=0")
if a.lz4:
    subprocess.run([sys.executable, str(here / "apply_lz4.py"), "--kernel", str(stage)], check=True)
    assert not list(stage.rglob("*.rej"))
    print("PASS: complete C1 LZ4/LZ4KD patch replay, zero rejects, fuzz=0")
