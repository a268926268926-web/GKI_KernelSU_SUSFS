#!/usr/bin/env python3
"""Apply the pinned BBRv3 backport for C2 and later stages."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

here = Path(__file__).resolve().parent
common = here.parent / "kernel/common"
locks = json.loads((here / "locks.json").read_text())
patch = here / "patches/network/0001-net-tcp-backport-BBRv3-to-android16-6.12.patch"
locked = locks["network_patches"]["bbrv3"]

actual = hashlib.file_digest(patch.open("rb"), "sha256").hexdigest()
assert actual == locked["sha256"], (actual, locked["sha256"])
assert not list(common.rglob("*.rej")), "Residual rejects before BBRv3"

payload = patch.read_text()

# Linux 6.12.81 inserted tcp_in_ack_event() into the tcp_ack TLP path after
# this backport's base revision. Skip that exact context-dependent hunk and
# make its one-line call-site change programmatically after the rest applies.
sections = re.split(r"(?=^diff --git )", payload, flags=re.M)
for index, section in enumerate(sections):
    if not section.startswith("diff --git a/net/ipv4/tcp_input.c "):
        continue
    chunks = re.split(r"(?=^@@ )", section, flags=re.M)
    adapted = 0
    for hunk_index, chunk in enumerate(chunks):
        if ("tcp_rack_update_reo_wnd(sk, &rs);" not in chunk or
                "tcp_process_tlp_ack(sk, ack, flag);" not in chunk):
            continue
        chunks[hunk_index] = ""
        adapted += 1
    assert adapted == 1, adapted
    sections[index] = "".join(chunks)
    break
else:
    raise AssertionError("BBRv3 tcp_input TLP hunk not found")

payload = "".join(sections)
with tempfile.TemporaryDirectory(prefix="bbrv3-integrate-") as temp:
    temp_patch = Path(temp) / patch.name
    temp_patch.write_text(payload)
    subprocess.run(
        ["patch", "--batch", "--fuzz=0", "-p1", "--dry-run"],
        cwd=common,
        input=payload.encode(),
        check=True,
    )
    subprocess.run(
        ["patch", "--batch", "--fuzz=0", "-p1", "--no-backup-if-mismatch"],
        cwd=common,
        input=payload.encode(),
        check=True,
    )

tcp_input = common / "net/ipv4/tcp_input.c"
source = tcp_input.read_text()
old_call = "tcp_process_tlp_ack(sk, ack, flag);"
new_call = "tcp_process_tlp_ack(sk, ack, flag, &rs);"
assert source.count(old_call) == 1
source = source.replace(old_call, new_call, 1)
tcp_input.write_text(source)

assert not list(common.rglob("*.rej")), "BBRv3 patch produced rejects"
assert (common / "net/ipv4/tcp_bbr3.c").is_file()
kconfig = common / "net/ipv4/Kconfig"
source = kconfig.read_text()
wrong_condition = 'default "bbr3" if DEFAULT_BBR\n'
right_condition = 'default "bbr3" if DEFAULT_BBR3\n'
assert source.count(wrong_condition) == 1
kconfig.write_text(source.replace(wrong_condition, right_condition, 1))
source = kconfig.read_text()
assert "config TCP_CONG_BBR3" in source
assert "config DEFAULT_BBR3" in source
assert right_condition in source
print("PASS: pinned BBRv3 6.12 backport applied with zero rejects and corrected default selection")
