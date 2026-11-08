#!/usr/bin/env python3
"""Integrate the pinned Re:Kernel core and network support into common."""
import json
from pathlib import Path
import re
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

# The pinned 6.12.96 Binder code uses a local snapshot of proc->is_frozen.
# Keep Android's native handling and extend only the async update condition.
binder_path = common / "drivers/android/binder.c"
signal_path = common / "kernel/signal.c"
binder_before = binder_path.read_text()
signal_before = signal_path.read_text()
native_frozen = "if ((t->flags & TF_UPDATE_TXN) && frozen) {"
assert binder_before.count(native_frozen) == 1, "Unexpected Binder frozen branch"
assert "binder_find_outdated_transaction_ilocked" in binder_before
signal_anchor = "trace_android_vh_do_send_sig_info(sig, current, p);"
assert signal_before.count(signal_anchor) == 1, "Ambiguous signal hook anchor"
signal_start = signal_before.index("int do_send_sig_info(")
signal_end = signal_before.index("\n}", signal_start)
assert signal_start < signal_before.index(signal_anchor) < signal_end

upstream_script = source / "Integrate/patches.sh"
script = upstream_script.read_text()
script = script.replace(
    "arch/arm64/configs/defconfig",
    "arch/arm64/configs/gki_defconfig",
)
assert "gki_defconfig" in script
# The upstream global -ESRCH address also matches __kill_pgrp_info before
# its p=NULL target is populated. That path already calls do_send_sig_info
# for each target, so insert exactly once at the unique per-task trace hook.
old_signal_address = "sed -i '/int ret = -ESRCH;/a"
assert script.count(old_signal_address) == 1
script = script.replace(old_signal_address, f"sed -i '/{signal_anchor}/a", 1)
old_frozen = "if ((t->flags & TF_UPDATE_TXN) && proc->is_frozen) {"
assert script.count(old_frozen) == 2
script = script.replace(old_frozen, native_frozen)
rekernel_frozen = "if ((t->flags & TF_UPDATE_TXN) && frozen_task_group(proc->tsk)) {"
assert script.count(rekernel_frozen) == 2
combined_frozen = "if ((t->flags & TF_UPDATE_TXN) && (frozen || frozen_task_group(proc->tsk))) {"
existing_branch_start = script.index("if grep -q 'binder_find_outdated_transaction_ilocked' $i; then")
existing_branch_end = script.index("\n\t\telse\n", existing_branch_start)
existing_branch = script[existing_branch_start:existing_branch_end]
assert existing_branch.count(rekernel_frozen) == 1
script = (script[:existing_branch_start] +
          existing_branch.replace(rekernel_frozen, combined_frozen, 1) +
          script[existing_branch_end:])

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

# The upstream script can silently continue after missing anchors. Require
# every event path, and bind the only signal report to the intended function.
binder = binder_path.read_text()
for hook in [
    "#include <../rekernel/rekernel.h>",
    "void rekernel_binder_transaction(bool reply",
    "binder_reply_handler(task_tgid_nr(current)",
    "binder_trans_handler(t->from->proc->pid",
    "binder_trans_handler(task_tgid_nr(current)",
    "binder_overflow_handler(task_tgid_nr(current)",
    "rekernel_binder_transaction(reply, t, target_node, tr);",
    combined_frozen,
]:
    assert binder.count(hook) == 1, ("Missing or duplicate Binder hook", hook)
assert re.search(
    r"#ifdef CONFIG_REKERNEL\n\s*" + re.escape(combined_frozen) +
    r"\n#else\n\s*" + re.escape(native_frozen) + r"\n#endif", binder
), "Native Binder frozen fallback was not retained"
signal = signal_path.read_text()
signal_report = "rekernel_report(SIGNAL, sig, task_tgid_nr(current), current, task_tgid_nr(p), p, false, NULL);"
assert signal.count(signal_report) == 1, "Signal hook must report per task exactly once"
signal_start = signal.index("int do_send_sig_info(")
signal_end = signal.index("\n}", signal_start)
assert signal_start < signal.index(signal_anchor) < signal.index(signal_report) < signal_end
assert "#include <../drivers/rekernel/rekernel.h>" in signal

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
