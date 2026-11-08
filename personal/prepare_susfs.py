#!/usr/bin/env python3
"""Use native BakaSU interfaces and preserve the locked kernel's rollup flow."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from prepare_bakasu import prepare

p = argparse.ArgumentParser()
p.add_argument("kernel", type=Path)
p.add_argument("bakasu", type=Path)
p.add_argument("susfs", type=Path)
p.add_argument("--check-only", action="store_true")
a = p.parse_args()
locks = json.loads((Path(__file__).parent / "locks.json").read_text())
for path, key in [(a.bakasu, "BakaSU"), (a.susfs, "susfs4ksu")]:
    head = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    assert head == locks["components"][key]["commit"], (key, head)
prepare(a.bakasu, locks, check_only=True)
k = a.bakasu / "kernel"
contracts = {
    "preinit/preinit.c": ["int ksu_setup_preinit_file(", "int ksu_preinit_handle_post_execveat("],
    "feature/selinux_hide.c": ["#define ksu_handle_selinux_setprocattr my_setprocattr", "my_write_context(", "my_write_access(", "KSU_COMPAT_HAS_SUSFS_FEATURE_SELINUX_HIDE"],
    "tools/susfs_compat.mk": ["-DKSU_COMPAT_HAS_SUSFS_FEATURE_SELINUX_HIDE", "ksu_selinux_hide_running"],
    "tools/code_generation/preinit_runner/preinit_runner.mk": ["kernelsu-objs += preinit/preinit.o", "kernelsu-objs += preinit/blob.o"],
    "tools/code_generation/code_generation.mk": ["preinit_runner/preinit_runner.mk"],
    "Kbuild": ["tools/code_generation/code_generation.mk", "tools/susfs_compat.mk"],
}
for file, needles in contracts.items():
    source = (k / file).read_text()
    for needle in needles:
        assert needle in source, (file, needle)
assert not (k / "bakasu_susfs_compat.c").exists(), "Obsolete stub must not be present"
assert "Please wait susfs update" not in (k / "tools/susfs_compat.mk").read_text()
patch = (a.susfs / "kernel_patches/50_add_susfs_in_gki-android16-6.12.patch").read_text()
source_path = a.kernel / "fs/proc/task_mmu.c"
source = source_path.read_text()
start = source.index("static int show_smaps_rollup(")
end = source.index("\n#undef SEQ_PUT_DEC", start)
rollup = source[start:end]
assert "CONFIG_KSU_SUSFS_SUS_MAP" not in rollup
calls = re.findall(r"(?m)^([\t ]*)smap_gather_stats\(vma, &mss, (0|last_vma_end)\);$", rollup)
if len(calls) == 3 and "struct proc_maps_locking_ctx" not in rollup:
    # The pre-refactor kernel has three stats calls and its own retry path.
    # Replace only the two incompatible upstream hunks; retain every lock,
    # iterator and retry statement from that kernel.
    parts = re.split(r"(?=^@@ )", patch, flags=re.M)
    removed = [s for s in parts if s.startswith("@@ ") and "static int show_smaps_rollup" in s.splitlines()[0]]
    assert len(removed) == 2, "Unexpected SUSFS rollup patch layout"
    assert all("bypass_orig_flow" in s for s in removed)
    adapted = "".join(s for s in parts if s not in removed)

    def guard(match):
        indent = match.group(1)
        return ("#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n" + indent +
                "if (!(vma->vm_file && SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))))\n" +
                "#endif\n" + indent + "\tsmap_gather_stats(vma, &mss, " + match.group(2) + ");")

    new_rollup = re.sub(r"(?m)^([\t ]*)smap_gather_stats\(vma, &mss, (0|last_vma_end)\);$", guard, rollup)
    layout = "pre-refactor three-call rollup"
else:
    # 6.12.96 matches the locked SUSFS patch's native range-aware flow.
    # Reject unknown shapes rather than reverting newer VMA locking or
    # silently omitting either the whole-VMA or partial-range statistics.
    assert not calls, "Mixed old/new smaps_rollup stats calls"
    for anchor, count in {
        "struct proc_maps_locking_ctx *lock_ctx = &priv->lock_ctx;": 1,
        "vma = proc_get_vma(m, &pos);": 2,
        "smap_gather_stats_range(priv, vma, &mss, last_vma_end);": 1,
        "smap_gather_stats(priv, vma, &mss);": 1,
        "last_vma_end = vma->vm_end;": 1,
        "ret = lock_vma_range(m, lock_ctx);": 2,
        "unlock_vma_range(lock_ctx);": 1,
    }.items():
        assert rollup.count(anchor) == count, ("Unexpected native rollup layout", anchor)
    adapted = patch
    new_rollup = None
    layout = "native range-aware rollup"
if a.check_only:
    print(f"PASS: native BakaSU contracts and {layout}")
else:
    # Fail before mutation when the remaining upstream patch has any rejects.
    subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "--dry-run"], cwd=a.kernel, input=adapted, text=True, check=True)
    subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "--no-backup-if-mismatch"], cwd=a.kernel, input=adapted, text=True, check=True)
    if new_rollup is not None:
        after = source_path.read_text()
        assert after.count(rollup) == 1
        source_path.write_text(after.replace(rollup, new_rollup, 1))
    print(f"PASS: SUSFS applied; {layout} lock/retry logic retained")
