#!/usr/bin/env python3
"""Keep NFT state in its existing private allocation, preserving struct net."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

here = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--kernel", type=Path, default=here.parent / "kernel/common")
args = parser.parse_args()
common = args.kernel.resolve()
locks = json.loads((here / "locks.json").read_text())
locked = locks["network_patches"]["nft_pernet"]
assert locked["base_common"] == locks["common"], "NFT patch source lock differs"
patch = here / "patches/network" / locked["path"]
payload = patch.read_bytes()
assert hashlib.sha256(payload).hexdigest() == locked["sha256"]
assert not list(common.rglob("*.rej")), "Residual rejects before NFT integration"

# Dry-run all hunks before changing any source. Keep normal symbol versioning;
# restoring real storage/layout is the fix, rather than suppressing its CRC.
subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "--dry-run"],
               cwd=common, input=payload, check=True)
subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "--no-backup-if-mismatch"],
               cwd=common, input=payload, check=True)
namespace = (common / "include/net/net_namespace.h").read_text()
assert not re.search(r"struct netns_nftables\s+nft\s*;", namespace)
header = (common / "include/net/netfilter/nf_tables.h").read_text()
assert header.count("struct netns_nftables\tnft;") == 1
assert "return &nft_pernet(net)->nft;" in header
files = [common / "include/net/netfilter/nf_tables.h", *[
    common / "net/netfilter" / name for name in
    ["nf_tables_api.c", "nf_tables_core.c", "nft_lookup.c"]]]
assert sum(p.read_text().count("nft_netns(net)->") for p in files) == 8
for directory in [common / "include", common / "net"]:
    for path in directory.rglob("*.[ch]"):
        assert not re.search(r"\bnet\s*->\s*nft\b", path.read_text(errors="replace")), path
assert not list(common.rglob("*.rej")), "NFT patch produced rejects"
print("PASS: NFT state uses existing per-net allocation; public struct net unchanged")
