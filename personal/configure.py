#!/usr/bin/env python3
"""Apply the approved A/B baseline and staged C feature choices."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

here = Path(__file__).resolve().parent
common = here.parent / "kernel/common"
variant = os.environ.get("BUILD_VARIANT", "A")
assert variant in {"A", "B", "C1", "C2", "C3", "C"}
is_c = variant.startswith("C")
has_network = variant in {"C2", "C3", "C"}
has_root_container = variant in {"C3", "C"}
locks = json.loads((here / "locks.json").read_text())
if variant == "B" or is_c:
    source = here / "adios/adios.c"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == locks["adios"]["sha256"]
    shutil.copy2(source, common / "block/adios.c")
    kconfig = common / "block/Kconfig.iosched"
    src = kconfig.read_text()
    assert "config MQ_IOSCHED_ADIOS" not in src
    assert 'endmenu' in src
    src = src.replace("endmenu", 'config MQ_IOSCHED_ADIOS\n\ttristate "Adaptive Deadline I/O Scheduler"\n\tdepends on BLOCK\n\tdefault n\n\thelp\n\t  Optional ADIOS 3.1.9 scheduler. Select per block device at runtime.\n\nendmenu', 1)
    kconfig.write_text(src)
    makefile = common / "block/Makefile"
    makefile.write_text(makefile.read_text() + "\nobj-$(CONFIG_MQ_IOSCHED_ADIOS) += adios.o\n")

# CONFIG_DEFAULT_IOSCHED does not exist in this blk-mq kernel. Keep its
# mq-deadline selection policy unchanged, and retain the scheduler built in.
required = {
    "CONFIG_KSU": "y", "CONFIG_KSU_SUSFS": "y",
    "CONFIG_KSU_TRACEPOINT_HOOK": "n", "CONFIG_KSU_MANUAL_HOOK": "n",
    "CONFIG_KSU_MULTI_MANAGER_SUPPORT": "n", "CONFIG_KSU_TOOLKIT_SUPPORT": "y",
    "CONFIG_BBG": "y", "CONFIG_NOMOUNT": "y", "CONFIG_MQ_IOSCHED_DEADLINE": "y",
    "CONFIG_MQ_IOSCHED_ADIOS": "y" if variant == "B" or is_c else "n",
    "CONFIG_HEADERS_INSTALL": "y", "CONFIG_ARM64_4K_PAGES": "y",
    "CONFIG_ARM64_16K_PAGES": "n", "CONFIG_ARM64_64K_PAGES": "n",
}
if is_c:
    required.update({
        "CONFIG_ZRAM": "y",
        "CONFIG_ZSMALLOC": "y",
        "CONFIG_KERNEL_MODE_NEON": "y",
        "CONFIG_LZ4_COMPRESS": "y",
        "CONFIG_LZ4_DECOMPRESS": "y",
        "CONFIG_CRYPTO_LZO": "y",
        "CONFIG_CRYPTO_LZ4": "y",
        "CONFIG_CRYPTO_LZ4K": "y",
        "CONFIG_CRYPTO_LZ4KD": "y",
        "CONFIG_LZ4K_COMPRESS": "y",
        "CONFIG_LZ4K_DECOMPRESS": "y",
        "CONFIG_LZ4KD_COMPRESS": "y",
        "CONFIG_LZ4KD_DECOMPRESS": "y",
        "CONFIG_CRYPTO_LZ4HC": "n",
        "CONFIG_CRYPTO_842": "n",
        "CONFIG_ZRAM_BACKEND_LZ4": "y",
        "CONFIG_ZRAM_BACKEND_LZ4K": "y",
        "CONFIG_ZRAM_BACKEND_LZ4KD": "y",
        "CONFIG_ZRAM_BACKEND_LZ4HC": "n",
        "CONFIG_ZRAM_BACKEND_842": "n",
        "CONFIG_ZRAM_DEF_COMP_LZORLE": "n",
        "CONFIG_ZRAM_DEF_COMP_LZ4": "n",
        "CONFIG_ZRAM_DEF_COMP_LZ4K": "n",
        "CONFIG_ZRAM_DEF_COMP_LZ4KD": "y",
        "CONFIG_ZRAM_DEF_COMP": '"lz4kd"',
    })
if has_network:
    required.update({
        "CONFIG_TCP_CONG_BBR": "y",
        "CONFIG_TCP_CONG_BBR3": "y",
        "CONFIG_TCP_CONG_VEGAS": "y",
        "CONFIG_TCP_CONG_NV": "y",
        "CONFIG_DEFAULT_TCP_CONG": '"bbr3"',
        "CONFIG_NF_TABLES": "y",
        "CONFIG_NF_TABLES_INET": "y",
        "CONFIG_NF_TABLES_IPV4": "y",
        "CONFIG_NF_TABLES_IPV6": "y",
        "CONFIG_NF_TABLES_NETDEV": "y",
        "CONFIG_NFT_CT": "y",
        "CONFIG_NFT_NAT": "y",
        "CONFIG_NFT_MASQ": "y",
        "CONFIG_NFT_REDIR": "y",
        "CONFIG_NFT_COMPAT": "y",
        "CONFIG_NFT_FIB_INET": "y",
        "CONFIG_NET_SCH_PIE": "y",
    })
if has_root_container:
    required.update({
        "CONFIG_BT": "m",
        "CONFIG_BT_HCIVHCI": "m",
        "CONFIG_REKERNEL": "y",
        "CONFIG_REKERNEL_NETWORK": "y",
    })
defconfig = common / "arch/arm64/configs/gki_defconfig"
src = defconfig.read_text()
for key, value in required.items():
    src = re.sub(rf"(?m)^(?:{key}=.*|# {key} is not set)\n?", "", src)
    src += f"{key}={value}\n"
# C1 has no BBRv3 source patch yet. Later C stages add it explicitly.
if not has_network:
    src = re.sub(r"(?m)^CONFIG_TCP_CONG_BBR3=.*\n?", "", src)
defconfig.write_text(src)

# Use actual config.gz generated from the real .config; no stock substitution.
build = common / "BUILD.bazel"
src = build.read_text()
anchor = '    name = "kernel_aarch64",'
assert src.count(anchor) == 1
# This pinned common_kernel wrapper already retains .config and Module.symvers;
# it does not expose the lower-level kernel_build keep_* attributes.
src = src.replace(anchor, anchor + '\n    check_defconfig = "disabled",', 1)
build.write_text(src)

# Guard source version independently from filenames or workflow input values.
make = (common / "Makefile").read_text()
version = ".".join(re.search(rf"(?m)^{key}\s*=\s*(\d+)\s*$", make).group(1) for key in ["VERSION", "PATCHLEVEL", "SUBLEVEL"])
assert version == locks["version"], version
assert not list(common.rglob("*.rej")), "Residual patch rejects"
print(f"Prepared {version} 4K, variant {variant}; scheduler policy retained")
