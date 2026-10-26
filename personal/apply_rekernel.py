#!/usr/bin/env python3
"""Integrate the pinned Re:Kernel core and network support into common."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

here = Path(__file__).resolve().parent
workspace = here.parent
common = workspace / "kernel/common"
source = workspace / "Re-Kernel"
locks = json.loads((here / "locks.json").read_text())
locked = locks["components"]["Re-Kernel"]["commit"]

head = subprocess.check_output(
    ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
).strip()
assert head == locked, (head, locked)
assert not (common / "drivers/rekernel").exists(), "Re:Kernel already present"
assert not list(common.rglob("*.rej")), "Residual rejects before Re:Kernel"

upstream_script = source / "Integrate/patches.sh"
script = upstream_script.read_text()
script = script.replace(
    "arch/arm64/configs/defconfig",
    "arch/arm64/configs/gki_defconfig",
)
assert "gki_defconfig" in script

with tempfile.TemporaryDirectory(prefix="rekernel-integrate-") as temp:
    temp = Path(temp)
    shutil.copytree(source / "Integrate/rekernel", temp / "rekernel")
    adapted = temp / "patches.sh"
    adapted.write_text(script)
    subprocess.run(["bash", str(adapted)], cwd=common, check=True)

assert (common / "drivers/rekernel/Kconfig").is_file()
assert (common / "drivers/rekernel/rekernel.c").is_file()
assert "source \"drivers/rekernel/Kconfig\"" in (common / "drivers/Kconfig").read_text()
assert "obj-$(CONFIG_REKERNEL) += rekernel/" in (common / "drivers/Makefile").read_text()
assert "CONFIG_REKERNEL=y" in (
    common / "arch/arm64/configs/gki_defconfig"
).read_text()

# Re:Kernel currently formats an unsigned long as int and provides two binder
# fields that are absent from the non-feedback log format. Both become hard
# -Wformat errors with the Android 6.12 Clang flags.
rekernel = common / "drivers/rekernel/rekernel.c"
source = rekernel.read_text()
for old, new in [
    ('seq_printf(m, "%d\\n", netlink_unit);',
     'seq_printf(m, "%lu\\n", netlink_unit);'),
    ('pr_info("Created Re:Kernel server! NETLINK UNIT: %d\\n", netlink_unit);',
     'pr_info("Created Re:Kernel server! NETLINK UNIT: %lu\\n", netlink_unit);'),
    ('sprintf(buff, "%d", netlink_unit);',
     'sprintf(buff, "%lu", netlink_unit);'),
    ('"type=Binder,bindertype=%s,oneway=%d,from_pid=%d,from=%d,target_pid=%d,target=%d;"',
     '"type=Binder,bindertype=%s,oneway=%d,from_pid=%d,from=%d,target_pid=%d,target=%d,rpc_name=%s,code=%d;"'),
]:
    assert source.count(old) == 1, old
    source = source.replace(old, new, 1)
rekernel.write_text(source)

assert not list(common.rglob("*.rej")), "Re:Kernel integration produced rejects"
print("PASS: pinned Re:Kernel core and Network hooks integrated")
