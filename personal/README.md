# OnePlus 15 personal build

Target: Android 16 kernel family, Linux 6.12.81, June 2026 source snapshot,
4 KiB pages. This is a build candidate until separately tested on the device.

`locks.json` records all selected component commits. `manifest.xml` pins all
50 AOSP projects to the matching superproject tree, including the compiler.
`generate_manifest.py` regenerates it only from that exact manifest and
superproject. `verify_manifest.py` checks every checkout before patching.

The dedicated workflow runs A on this branch's pushes. B is dispatched with
`variant=B` only after a successful A at the same workflow commit. Pushes never
flash a phone or publish a GitHub Release. Artifacts expire after 30 days;
download the candidate and evidence for durable local archiving.

A retains the selected Wild functionality: BakaSU, SUSFS, NoMount kernel
support, Baseband Guard, container namespaces/IPC, NTSync, BTF/eBPF/FUSE-BPF,
network/firewall options, CIFS and Unicode compatibility. The 6.12 baseline
has BBR; BBRv3 is not claimed because its source patch is not enabled upstream.
Perf and module version mismatch bypass remain disabled. The true generated
configuration is used, including for embedded config.gz.

B adds only the pinned ADIOS 3.1.9 source, Kconfig/Makefile registration and
`CONFIG_MQ_IOSCHED_ADIOS=y`. It does not change blk-mq's scheduler selection
policy; mq-deadline remains built in. ADIOS is an I/O scheduler, not a CPU
scheduler. No constant userspace process is added; performance/power effects
when selected require device measurements.

Compatibility changes are narrow and recorded in exported diffs:

- Native BakaSU preinit and SELinux interfaces replace the old stub injection.
- The exact upstream `d5e9e025` code-generator guard is backported to the
  selected `c0c96a40` candidate. The candidate UAPI remains 6.
- Kbuild uses an absolute path to the pinned BakaSU source, as its own Bazel
  integration instructions require; real upstream hook checks stay enabled.
- Two incompatible SUSFS rollup hunks are replaced by filtering at all three
  6.12.81 statistics calls. mmap lock/retry/iterator behavior is preserved.
- Defconfig checking is disabled for the deliberately customized target;
  explicit required settings are checked in the actual generated `.config`.
- Wild's module export policy is retained. This is not proof of vendor module
  ABI compatibility; `Module.symvers`, System.map and vmlinux are exported.

The evidence artifact contains the resolved manifest, locks, component and
kernel diffs, added/changed files, actual final config, compiler versions,
build log, symbols and acceptance record. The delivery artifact contains an
actual AnyKernel3 ZIP, Image and their SHA256 hashes. Manager 35251 from the
official pinned BakaSU run is paired separately; neither Manager nor NoMount
metamodule is silently installed or treated as bundled in the kernel ZIP.

For maintenance, update a compatible component set on this branch, review
the changed source contracts, replay patches, then build A before B. Keep the
last working locks, candidate ZIP, Manager and evidence together. A ROM/vendor
update requires fresh KMI, page-size and vendor module checks. Keep new network,
compression or scheduling experiments in separate minimal changes.
