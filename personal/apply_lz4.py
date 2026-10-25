#!/usr/bin/env python3
"""Apply the pinned LZ4 1.10 and LZ4K/LZ4KD source chain."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

here = Path(__file__).resolve().parent
common = here.parent / "kernel/common"
locks = json.loads((here / "locks.json").read_text())
locked = locks["lz4_patches"]
backend_locks = locks["lz4_backends"]


def digest(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


# Ordering matters: the LZ4K/LZ4KD backend uses the patched lib/lz4 API.
patches = [here / "patches/lz4/001-lz4.patch",
           here / "patches/lz4/lz4kd.patch"]
for patch in patches:
    expected = locked["files"][patch.name]
    actual = digest(patch)
    assert actual == expected, (patch.name, actual, expected)
for name, expected in backend_locks["files"].items():
    actual = digest(here / "lz4" / name)
    assert actual == expected, (name, actual, expected)

assert not list(common.rglob("*.rej")), "Residual rejects before LZ4 patches"

# The CCTV patch also removes an obsolete vendor F2FS LZ4 accelerator. The
# pinned AOSP June snapshot already has the desired post-patch state. Omitting
# only an already-satisfied hunk avoids rejecting the complete patch.
def adapt_upstream_lz4(source):
    sections = re.split(r"(?=^diff --git )", source, flags=re.M)
    keep = []
    for section in sections:
        if section.startswith("diff --git a/fs/f2fs/Makefile "):
            target = (common / "fs/f2fs/Makefile").read_text()
            if "CONFIG_F2FS_FS_COMPRESSION_FIXED_OUTPUT" not in target:
                print("SKIP: obsolete F2FS Makefile accelerator hunk already satisfied")
                continue
        if section.startswith("diff --git a/fs/f2fs/compress.c "):
            target = (common / "fs/f2fs/compress.c").read_text()
            if "lz4armv8/lz4accel.h" not in target:
                print("SKIP: obsolete F2FS compressor include hunk already satisfied")
                continue
        keep.append(section)
    return "".join(keep)

adapted = {}
for patch in patches:
    payload = patch.read_bytes()
    if patch.name == "001-lz4.patch":
        payload = adapt_upstream_lz4(payload.decode()).encode()
    adapted[patch.name] = payload

with tempfile.TemporaryDirectory(prefix="lz4-integrate-") as temp:
    for patch in patches:
        payload = adapted[patch.name]
        temp_patch = Path(temp) / patch.name
        temp_patch.write_bytes(payload)
        subprocess.run(
            ["patch", "--batch", "--fuzz=0", "-p1", "--dry-run"],
            cwd=common,
            input=payload,
            check=True,
        )
        subprocess.run(
            ["patch", "--batch", "--fuzz=0", "-p1", "--no-backup-if-mismatch"],
            cwd=common,
            input=payload,
            check=True,
        )

assert not list(common.rglob("*.rej")), "LZ4 patch produced rejects"

# The public CCTV patch adds the proprietary codec libraries but its ZRAM
# backend mistakenly calls the standard LZ4 API with different acceleration
# values. Keep the complete upstream patch, then wire each ZRAM backend to its
# matching lz4k/lz4kd implementation.
zram = common / "drivers/block/zram"
upstream_backend = (zram / "backend_lz4kd.c").read_text()
assert "LZ4KD_ACCELERATION" in upstream_backend
assert "LZ4_compress_fast" in upstream_backend
makefile = zram / "Makefile"
source = makefile.read_text()
old_makefile = """\
ifneq ($(CONFIG_ZRAM_BACKEND_LZ4K)$(CONFIG_ZRAM_BACKEND_LZ4KD),)
\tzram-y += backend_lz4kd.o
endif
"""
new_makefile = """\
zram-$(CONFIG_ZRAM_BACKEND_LZ4K)\t+= backend_lz4k.o
zram-$(CONFIG_ZRAM_BACKEND_LZ4KD)\t+= backend_lz4kd.o
"""
assert source.count(old_makefile) == 1
makefile.write_text(source.replace(old_makefile, new_makefile, 1))
shutil.copy2(here / "lz4/backend_lz4k.c", zram / "backend_lz4k.c")
shutil.copy2(here / "lz4/backend_lz4kd.c", zram / "backend_lz4kd.c")
for name, encoder, decoder in [
    ("backend_lz4k.c", "lz4k_encode(", "lz4k_decode("),
    ("backend_lz4kd.c", "lz4kd_encode(", "lz4kd_decode("),
]:
    backend = (zram / name).read_text()
    assert encoder in backend and decoder in backend
    assert "LZ4_compress_fast" not in backend

for relative in [
    "lib/lz4/lz4armv8/lz4armv8.S",
    "lib/lz4k/lz4k_encode.c",
    "lib/lz4kd/lz4kd_encode.c",
    "drivers/block/zram/backend_lz4k.c",
    "drivers/block/zram/backend_lz4kd.c",
    "include/linux/lz4k.h",
    "include/linux/lz4kd.h",
]:
    assert (common / relative).is_file(), f"Missing LZ4 source: {relative}"

print("PASS: pinned LZ4 1.10 and real LZ4K/LZ4KD backends applied with zero rejects")
