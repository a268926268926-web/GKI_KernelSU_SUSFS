# OnePlus 15 personal build

Baseline: WildKernels **r22**, commit
`8d8e03391f26677b033d3c27face86a738a6a319`. The branch is based directly on
that release; personal features are migrated from `dc557601`. The Android
source/compiler snapshot remains fixed separately below. A builder release
update does not require changing Linux version, KMI or the compiler snapshot.

Target: Android 16 kernel family, Linux 6.12.81, June 2026 source snapshot,
4 KiB pages. This is a build candidate until separately tested on the device.

`locks.json` records all selected component commits. `manifest.xml` pins all
50 AOSP projects to the matching superproject tree, including the compiler.
`generate_manifest.py` regenerates it only from that exact manifest and
superproject. `verify_manifest.py` checks every checkout before patching.

The dedicated workflow runs C1 on the R22 branch's pushes. The old BakaSU
baseline branch still defaults to A. B is dispatched with
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
- BakaSU is pinned to R22's `d5e9e025`, driver 35252 / UAPI 6. Its code-generator
  guard is native; the former two-line backport is no longer applied.
- SUSFS is pinned to R22's `519c86c5`, still v2.3.0. `prepare_bakasu.py` wires
  its added command into BakaSU's dispatcher and refreshes its package mapping
  from the deferred package observer. It does not replace native hooks with
  compatibility stubs or start a worker inside the fsnotify fallback.
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
actual AnyKernel3 ZIP, Image and their SHA256 hashes. Embedded config must
match the true final configuration byte for byte; R22's stock-config embedding
action is deliberately not called by this workflow. Manager 35252 from the
official pinned BakaSU run is paired separately; neither Manager nor NoMount
metamodule is silently installed or treated as bundled in the kernel ZIP.

NoMount follows R22's `e7f7c676`, driver protocol **22**. Its matching
metamodule is a separate deployment prerequisite; the old protocol-21 pairing
must not be assumed compatible. The kernel workflow never installs it.

The existing AnyKernel3, kernel_patches, DroidSpaces kernel-patch, Baseband
Guard and Re-Kernel commits remain independently locked. R22 resolves some of
these from moving branches: retaining explicit audited pins is deliberate.
No unverified claim is made that R22 fixed Baseband Guard/relock compatibility.

Deliver and validate **C1 -> C2 -> C3 -> final C**. C2D1/C2D2 are historical
diagnostic options, not extra delivery stages. A prior successful CI build is
only a build dependency, not device acceptance. C2's recorded vendor-module
ABI regression remains unresolved; update the driver snapshot for the actual
ROM and resolve it before another phone test. B's slow boot also remains an
open measurement question. Do not change selected features to hide either issue.

Re-Kernel remains a selected C3 capability. It reports events to compatible
userspace clients; it does not choose or freeze apps by itself. A third-party
freezer is optional and should be evaluated separately from kernel support.

For maintenance, update a compatible component set on this branch, review
the changed source contracts, replay patches, then build A before B. Keep the
last working locks, candidate ZIP, Manager and evidence together. A ROM/vendor
update requires fresh KMI, page-size and vendor module checks. Keep new network,
compression or scheduling experiments in separate minimal changes.
