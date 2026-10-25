#!/usr/bin/env python3
"""Package the optional virtual HCI module from the Kleaf staging tree."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import zipfile

here = Path(__file__).resolve().parent
workspace = here.parent
kernel = workspace / "kernel"
delivery = workspace / "deliverables"
evidence = workspace / "evidence"
source_module = kernel / "bazel-bin/common/kernel_aarch64"
variant = os.environ.get("BUILD_VARIANT", "")

assert variant in {"C3", "C"}, f"Optional HCI module is not part of {variant!r}"
matches = sorted(source_module.rglob("hci_vhci.ko"))
assert len(matches) == 1, [str(item) for item in matches]
module = matches[0]
assert module.stat().st_size > 0
module_bytes = module.read_bytes()
assert module_bytes[:4] == b"\x7fELF", "hci_vhci.ko is not ELF"
assert module_bytes[4:6] == b"\x02\x01", "hci_vhci.ko is not 64-bit little-endian"
assert int.from_bytes(module_bytes[18:20], "little") == 183, "hci_vhci.ko is not AArch64"

image = source_module / "Image"
banner = re.search(rb"Linux version ([^\s\x00]+)", image.read_bytes())
assert banner, "Final Image version banner absent"
expected_release = banner.group(1).decode()

staging = delivery / "extra-modules"
staging.mkdir(parents=True, exist_ok=True)
evidence.mkdir(parents=True, exist_ok=True)
shutil.copy2(module, staging / "hci_vhci.ko")
shutil.copy2(here / "modules/hci-vhci/module.prop", staging / "module.prop")
shutil.copy2(here / "modules/hci-vhci/service.sh", staging / "service.sh")

modinfo = subprocess.check_output(["modinfo", str(module)], text=True)
vermagic_lines = [line.removeprefix("vermagic:").strip() for line in modinfo.splitlines()
                  if line.startswith("vermagic:")]
assert len(vermagic_lines) == 1, modinfo
module_vermagic = vermagic_lines[0]
assert module_vermagic.startswith(expected_release + " "), (
    f"Module vermagic {module_vermagic!r} does not match kernel release {expected_release!r}"
)
(evidence / "hci_vhci.modinfo").write_text(modinfo)
shutil.copy2(module, evidence / "hci_vhci.ko")

package = delivery / "OnePlus15-C-hci-vhci-KernelSU.zip"
timestamp = time.gmtime(int(os.environ.get("SOURCE_DATE_EPOCH", "1780633200")))[:6]
with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for name in ["module.prop", "service.sh", "hci_vhci.ko"]:
        source = staging / name
        info = zipfile.ZipInfo(name, timestamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        mode = 0o755 if name.endswith(".sh") else 0o644
        info.external_attr = (stat.S_IFREG | mode) << 16
        archive.writestr(info, source.read_bytes(), compresslevel=9)
with zipfile.ZipFile(package) as archive:
    assert archive.testzip() is None
    service_mode = (archive.getinfo("service.sh").external_attr >> 16) & 0o777
    assert service_mode == 0o755, oct(service_mode)
    module_hash = hashlib.sha256(module_bytes).hexdigest()
    assert hashlib.sha256(archive.read("hci_vhci.ko")).hexdigest() == module_hash

record = {
    "module": "hci_vhci.ko",
    "kernel_release": expected_release,
    "vermagic": module_vermagic,
    "sha256": module_hash,
    "package": package.name,
}
(evidence / "hci_vhci.packaging.json").write_text(json.dumps(record, indent=2) + "\n")
print(f"PASS: packaged optional hci_vhci.ko ({module_hash})")
