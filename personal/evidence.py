#!/usr/bin/env python3
"""Export source provenance; require actual config and linked kernel evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

here = Path(__file__).resolve().parent
workspace = here.parent
kernel = workspace / "kernel"
common = kernel / "common"
evidence = workspace / "evidence"
delivery = workspace / "deliverables"
locks = json.loads((here / "locks.json").read_text())
variant = os.environ.get("BUILD_VARIANT", "A")
has_network = variant in {"C2", "C2D1", "C2D2", "C3", "C"}
has_bbr3 = variant in {"C2", "C2D2", "C3", "C"}
bbr3_default = variant in {"C2", "C3", "C"}
def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args])
def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()
def config_values(source):
    result = {}
    for line in source.splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
        elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
            result[line.split()[1]] = "n"
    return result
def require_config(config):
    required = {key: "y" for key in [
        "CONFIG_ARM64_4K_PAGES", "CONFIG_KSU", "CONFIG_KSU_SUSFS",
        "CONFIG_NOMOUNT", "CONFIG_BBG", "CONFIG_HEADERS_INSTALL",
        "CONFIG_KSU_TOOLKIT_SUPPORT", "CONFIG_MQ_IOSCHED_DEADLINE", "CONFIG_NTSYNC",
        "CONFIG_PID_NS", "CONFIG_USER_NS", "CONFIG_IPC_NS", "CONFIG_SYSVIPC", "CONFIG_POSIX_MQUEUE",
        "CONFIG_IP_SET", "CONFIG_NETFILTER_XT_SET", "CONFIG_TCP_CONG_BBR", "CONFIG_WIREGUARD",
        "CONFIG_DEBUG_INFO_BTF", "CONFIG_BPF_SYSCALL", "CONFIG_BPF_EVENTS", "CONFIG_FUSE_BPF",
        "CONFIG_KSU_SUSFS_SUS_PATH", "CONFIG_KSU_SUSFS_SUS_MOUNT", "CONFIG_KSU_SUSFS_SUS_KSTAT",
        "CONFIG_KSU_SUSFS_SPOOF_UNAME", "CONFIG_KSU_SUSFS_ENABLE_LOG", "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS",
        "CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG", "CONFIG_KSU_SUSFS_SUS_MAP", "CONFIG_KSU_SUSFS_OPEN_REDIRECT"
    ]}
    required.update({"CONFIG_KSU_TRACEPOINT_HOOK": "n", "CONFIG_KSU_MANUAL_HOOK": "n",
                     "CONFIG_KSU_MULTI_MANAGER_SUPPORT": "n", "CONFIG_DEFAULT_TCP_CONG": '"bbr"',
                     "CONFIG_MQ_IOSCHED_ADIOS": "y" if variant == "B" else "n"})
    if variant.startswith("C"):
        required.update({
            "CONFIG_ZRAM": "y", "CONFIG_ZSMALLOC": "y",
            "CONFIG_KERNEL_MODE_NEON": "y",
            "CONFIG_LZ4_COMPRESS": "y", "CONFIG_LZ4_DECOMPRESS": "y",
            "CONFIG_CRYPTO_LZ4": "y", "CONFIG_CRYPTO_LZ4K": "y", "CONFIG_CRYPTO_LZ4KD": "y",
            "CONFIG_LZ4K_COMPRESS": "y", "CONFIG_LZ4K_DECOMPRESS": "y",
            "CONFIG_LZ4KD_COMPRESS": "y", "CONFIG_LZ4KD_DECOMPRESS": "y",
            "CONFIG_CRYPTO_LZ4HC": "n", "CONFIG_CRYPTO_842": "n",
            "CONFIG_ZRAM_BACKEND_LZ4": "y", "CONFIG_ZRAM_BACKEND_LZ4K": "y",
            "CONFIG_ZRAM_BACKEND_LZ4KD": "y", "CONFIG_ZRAM_BACKEND_LZ4HC": "n",
            "CONFIG_ZRAM_BACKEND_842": "n", "CONFIG_ZRAM_DEF_COMP_LZ4KD": "y",
            "CONFIG_ZRAM_DEF_COMP": '"lz4kd"', "CONFIG_MQ_IOSCHED_ADIOS": "y",
        })
    if has_network:
        required.update({
            "CONFIG_TCP_CONG_BBR": "y",
            "CONFIG_TCP_CONG_VEGAS": "y", "CONFIG_TCP_CONG_NV": "y",
            "CONFIG_DEFAULT_CUBIC": "n",
            "CONFIG_NF_TABLES": "y", "CONFIG_NF_TABLES_INET": "y",
            "CONFIG_NF_TABLES_IPV4": "y", "CONFIG_NF_TABLES_IPV6": "y",
            "CONFIG_NF_TABLES_NETDEV": "y", "CONFIG_NFT_CT": "y",
            "CONFIG_NFT_NAT": "y", "CONFIG_NFT_MASQ": "y", "CONFIG_NFT_REDIR": "y",
            "CONFIG_NFT_COMPAT": "y", "CONFIG_NFT_FIB": "y",
            "CONFIG_NFT_FIB_IPV4": "y", "CONFIG_NFT_FIB_IPV6": "y",
            "CONFIG_NFT_FIB_INET": "y",
            "CONFIG_NET_SCH_PIE": "y",
        })
        if has_bbr3:
            required["CONFIG_TCP_CONG_BBR3"] = "y"
        else:
            required["CONFIG_TCP_CONG_BBR3"] = "n"
        if bbr3_default:
            required.update({
                "CONFIG_DEFAULT_BBR": "n", "CONFIG_DEFAULT_BBR3": "y",
                "CONFIG_DEFAULT_TCP_CONG": '"bbr3"',
            })
        else:
            required.update({
                "CONFIG_DEFAULT_BBR": "y", "CONFIG_DEFAULT_TCP_CONG": '"bbr"',
            })
            if has_bbr3:
                required["CONFIG_DEFAULT_BBR3"] = "n"
    if variant in {"C3", "C"}:
        required.update({
            "CONFIG_BT": "m", "CONFIG_BT_HCIVHCI": "m",
            "CONFIG_REKERNEL": "y", "CONFIG_REKERNEL_NETWORK": "y",
        })
    errors = {k: {"expected": v, "actual": config.get(k, "n")} for k, v in required.items() if config.get(k, "n") != v}
    assert not errors, json.dumps(errors, indent=2)
    assert config.get("CONFIG_ARM64_16K_PAGES", "n") == "n"
    assert config.get("CONFIG_ARM64_64K_PAGES", "n") == "n"
    assert "baseband_guard" in config.get("CONFIG_LSM", "").split(",") or "baseband_guard" in config.get("CONFIG_LSM", "")
    return required

if __name__ == "__main__":
    mode = sys.argv[1]
    evidence.mkdir(exist_ok=True)
    if mode == "source":
        assert not list(common.rglob("*.rej")), "Patch rejects present"
        (evidence / "common.patch").write_bytes(git(common, "diff", "--binary", "HEAD"))
        # Include new source files, symlinks and changes from all external
        # components; these remain separate repositories with exact base SHAs.
        locations = {"BakaSU": kernel / "BakaSU", "Baseband-guard": kernel / "Baseband-guard", "NoMount": common / "NoMount"}
        records = {}
        for name, lock in locks["components"].items():
            path = locations.get(name, workspace / name)
            actual = git(path, "rev-parse", "HEAD").decode().strip()
            assert actual == lock["commit"], (name, actual)
            (evidence / f"{name}.patch").write_bytes(git(path, "diff", "--binary", "HEAD"))
            records[name] = {**lock, "actual": actual}
        (evidence / "components.json").write_text(json.dumps(records, indent=2) + "\n")
        (evidence / "common-untracked.txt").write_bytes(git(common, "ls-files", "--others", "--exclude-standard"))
        # Archive the files listed above, not just a diff that omits new files.
        subprocess.run(["tar", "--exclude=.git", "--exclude=NoMount", "-czf", str(evidence / "common-changed-files.tar.gz"),
                        "--files-from", "-"], cwd=common,
                       input=git(common, "diff", "--name-only", "--diff-filter=ACMRT", "HEAD") + git(common, "ls-files", "--others", "--exclude-standard"), check=True)
        (evidence / "build-kernel.patch").write_bytes(git(kernel / "build/kernel", "diff", "--binary", "HEAD"))
        print("PASS: source provenance recorded; no patch rejects")
    elif mode == "package":
        output = kernel / "bazel-bin/common/kernel_aarch64"
        cfg = output / "kernel_aarch64_dot_config"
        assert cfg.is_file(), f"Real Kleaf final configuration missing: {cfg}"
        assert (output / "Image").is_file()
        required = require_config(config_values(cfg.read_text()))
        assert not list(common.rglob("*.rej"))
        log = (evidence / "build.log").read_text(errors="replace")
        assert "KSU_NO_PREINIT" not in log and "preinit disabled" not in log, "Native preinit disabled"
        system_map = (output / "System.map").read_text()
        for label, pattern in {
            "native preinit": r"\bksu_(?:setup_preinit_file|preinit_file)(?:\.|\s|$)",
            "native SELinux interface": r"\bmy_setprocattr(?:\.|\s|$)",
        }.items():
            assert re.search(pattern, system_map), f"Missing {label} in linked System.map"
        # The build rule's generated headers may not expose kernel.release.
        # Image's Linux version banner is the final linked version evidence.
        banner = re.search(rb"Linux version [^\x00\n]+", (output / "Image").read_bytes())
        assert banner, "Kernel version banner absent"
        banner_text = banner.group().decode(errors="replace")
        assert "6.12.81-android16" in banner_text, banner_text
        assert f"Personal{variant}" in banner_text, banner_text
        shutil.copy2(cfg, evidence / "final.config")
        shutil.copy2(output / "System.map", evidence / "System.map")
        shutil.copy2(output / "kernel_aarch64_Module.symvers", evidence / "Module.symvers")
        # Keep vmlinux independently compressed; it is evidence, not a flash file.
        with (evidence / "vmlinux.gz").open("wb") as compressed:
            subprocess.run(["gzip", "-c", str(output / "vmlinux")], stdout=compressed, check=True)
        compiler = sorted((kernel / "prebuilts/clang/host/linux-x86").glob("clang-*/bin/clang"))
        versions = {str(p.relative_to(kernel)): subprocess.check_output([str(p), "--version"], text=True).splitlines()[0] for p in compiler}
        delivery.mkdir(exist_ok=True)
        shutil.copy2(output / "Image", delivery / "Image")
        ak = workspace / "AnyKernel3"
        shutil.copy2(output / "Image", ak / "Image")
        package = delivery / f"OnePlus15-{variant}-6.12.81-android16-4k-AnyKernel3.zip"
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for file in sorted(ak.rglob("*")):
                rel = file.relative_to(ak)
                if file.is_file() and not any(part.startswith(".git") for part in rel.parts):
                    archive.write(file, str(rel))
        with zipfile.ZipFile(package) as archive:
            assert archive.testzip() is None
            assert hashlib.sha256(archive.read("Image")).hexdigest() == sha(delivery / "Image")
        record = {"variant": variant, "banner": banner_text, "compiler_versions": versions,
                  "final_config_sha256": sha(cfg), "required_config": required,
                  "device_tested": False, "allow_version_mismatch": False}
        (evidence / "acceptance.json").write_text(json.dumps(record, indent=2) + "\n")
        shutil.copy2(evidence / "acceptance.json", delivery / "acceptance.json")
        hashes = "".join(f"{sha(f)}  {f.name}\n" for f in sorted(delivery.iterdir()) if f.is_file() and f.name != "SHA256SUMS")
        (delivery / "SHA256SUMS").write_text(hashes)
        print(hashes)
        print("PASS: real config, native symbols, version, ZIP and Image accepted; device testing pending")
    else:
        raise SystemExit("Expected source or package")
