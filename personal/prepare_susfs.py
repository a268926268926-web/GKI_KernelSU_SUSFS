#!/usr/bin/env python3
"""Use native BakaSU interfaces and adapt only the locked 6.12.81 rollup."""
import argparse
import json
from pathlib import Path
import re
import subprocess

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
# The locked SUSFS patch targets a newer rollup implementation. Keep every
# other hunk byte-for-byte; apply equivalent filtering at all three original
# stats calls without changing this kernel's mmap_lock/retry/iterator logic.
parts = re.split(r"(?=^@@ )", patch, flags=re.M)
removed = [s for s in parts if s.startswith("@@ ") and "static int show_smaps_rollup" in s.splitlines()[0]]
assert len(removed) == 2, "Unexpected SUSFS rollup patch layout"
assert all("bypass_orig_flow" in s for s in removed)
adapted = "".join(s for s in parts if s not in removed)
source_path = a.kernel / "fs/proc/task_mmu.c"
source = source_path.read_text()
start = source.index("static int show_smaps_rollup(")
end = source.index("\n#undef SEQ_PUT_DEC", start)
rollup = source[start:end]
calls = re.findall(r"(?m)^(\s*)smap_gather_stats\(vma, &mss, (0|last_vma_end)\);$", rollup)
assert len(calls) == 3, "Unexpected 6.12.81 stats call layout"
assert "CONFIG_KSU_SUSFS_SUS_MAP" not in rollup
def guard(match):
    indent = match.group(1)
    return ("#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n" + indent +
            "if (!(vma->vm_file && SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))))\n" +
            "#endif\n" + indent + "\tsmap_gather_stats(vma, &mss, " + match.group(2) + ");")
new_rollup = re.sub(r"(?m)^([\t ]*)smap_gather_stats\(vma, &mss, (0|last_vma_end)\);$", guard, rollup)
if a.check_only:
    print("PASS: native BakaSU contracts and exactly three 6.12.81 rollup stats calls")
else:
    # Fail before mutation when the remaining upstream patch has any rejects.
    subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "--dry-run"], cwd=a.kernel, input=adapted, text=True, check=True)
    subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "--no-backup-if-mismatch"], cwd=a.kernel, input=adapted, text=True, check=True)
    after = source_path.read_text()
    assert after.count(rollup) == 1
    source_path.write_text(after.replace(rollup, new_rollup, 1))
    print("PASS: SUSFS applied; native rollup lock/retry logic retained")
