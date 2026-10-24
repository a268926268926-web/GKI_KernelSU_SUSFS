#!/usr/bin/env python3
"""Apply only the explicit baseline choices and optional ADIOS experiment."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

here = Path(__file__).resolve().parent
common = here.parent / "kernel/common"
variant = os.environ.get("BUILD_VARIANT", "A")
assert variant in {"A", "B"}
locks = json.loads((here / "locks.json").read_text())
if variant == "B":
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
    "CONFIG_MQ_IOSCHED_ADIOS": "y" if variant == "B" else "n",
    "CONFIG_HEADERS_INSTALL": "y", "CONFIG_ARM64_4K_PAGES": "y",
    "CONFIG_ARM64_16K_PAGES": "n", "CONFIG_ARM64_64K_PAGES": "n",
}
defconfig = common / "arch/arm64/configs/gki_defconfig"
src = defconfig.read_text()
for key, value in required.items():
    src = re.sub(rf"(?m)^(?:{key}=.*|# {key} is not set)\n?", "", src)
    src += f"{key}={value}\n"
# Wild 6.12 skips BBRv3's source patch; do not request a nonexistent option.
src = re.sub(r"(?m)^CONFIG_TCP_CONG_BBR3=.*\n?", "", src)
defconfig.write_text(src)

# Use actual config.gz generated from the real .config; no stock substitution.
build = common / "BUILD.bazel"
src = build.read_text()
anchor = '    name = "kernel_aarch64",'
assert src.count(anchor) == 1
src = src.replace(anchor, anchor + '\n    check_defconfig = "disabled",\n    keep_dot_config = True,\n    keep_module_symvers = True,', 1)
build.write_text(src)

# Guard source version independently from filenames or workflow input values.
make = (common / "Makefile").read_text()
version = ".".join(re.search(rf"(?m)^{key}\s*=\s*(\d+)\s*$", make).group(1) for key in ["VERSION", "PATCHLEVEL", "SUBLEVEL"])
assert version == locks["version"], version
assert not list(common.rglob("*.rej")), "Residual patch rejects"
print(f"Prepared {version} 4K, variant {variant}; native scheduler policy retained")
