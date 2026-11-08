#!/usr/bin/env python3
"""Fetch only files touched by SUSFS for a bounded local patch rehearsal."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

here = Path(__file__).resolve().parent
locks = json.loads((here / "locks.json").read_text())
scratch = Path(sys.argv[1]).resolve()
susfs = scratch / "susfs4ksu"
stage = scratch / "rehearsal"
assert not stage.exists(), "Use a fresh rehearsal directory"
patch = (susfs / "kernel_patches/50_add_susfs_in_gki-android16-6.12.patch").read_text()
paths = sorted(set(re.findall(r"(?m)^--- a/(\S+)", patch)))
def fetch(path):
    assert not path.startswith("/") and ".." not in Path(path).parts
    url = f"https://android.googlesource.com/kernel/common/+/{locks['common']}/{path}?format=TEXT"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = base64.b64decode(response.read())
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return path
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2)
with ThreadPoolExecutor(max_workers=6) as pool:
    fetched = list(pool.map(fetch, paths))
print(f"Fetched {len(fetched)} exact-source files", flush=True)
subprocess.run([sys.executable, str(here / "prepare_susfs.py"), str(stage), str(scratch / "BakaSU"), str(susfs)], check=True)
assert not list(stage.rglob("*.rej"))
print("PASS: complete SUSFS patch replay, zero rejects, fuzz=0")
