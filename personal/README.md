# OnePlus 15 personal build

Baseline: WildKernels **r22**, commit
`8d8e03391f26677b033d3c27face86a738a6a319`. The branch is based directly on
that release; personal features are migrated from `dc557601`. The Android
source/compiler snapshot remains fixed separately below. A builder release
update does not require changing Linux version, KMI or the compiler snapshot.

Target: Android 16 kernel family, Linux **6.12.96 LTS**, 4 KiB pages.
This is a personal LTS candidate using R22's builder/component baseline; it
does not claim to reproduce an R22 release binary. The complete source and
compiler snapshot is updated together, independently of the R22 tag.
This remains a build candidate until separately tested on the device.

`locks.json` records all selected component commits. `manifest.xml` pins all
AOSP projects to the matching superproject tree, including the compiler.
`generate_manifest.py` regenerates it only from that exact manifest and
superproject. `verify_manifest.py` checks every checkout, the actual Makefile
version and KMI constants before patching; a filename change cannot pass as
a kernel upgrade. It exports these verified values in source-snapshot.json.

The selected snapshot contains 51 projects. Linux's source commit time is
recorded as `source_commit_epoch`; the non-stamped Kleaf build deliberately
uses `source_date_epoch=0` (1970 UTC), verified against the actual Image
banner. ZIP metadata alone is clamped to 1980 for the ZIP format's date limit.

The dedicated workflow runs C1 on `oneplus15-6.12.96-r22` pushes.
B is dispatched with
`variant=B` only after a successful A at the same workflow commit. Pushes never
flash a phone or publish a GitHub Release. Artifacts expire after 30 days;
download the candidate and evidence for durable local archiving.

The personal workflow persists only Bazel's disk action cache and repository
download cache using pinned official Actions cache actions. Cache identity
includes the runner image, complete source/toolchain locks, recipe content,
page-size choices and stage; changed identities start cold. `use_cache=false`
on a manual run bypasses this cache. Entries larger than 4 GiB are not saved;
cache restore/save errors do not replace compilation or fail a valid build.
Cache identity, restored key, size and build duration are exported as evidence.
CI uses standard sandbox execution: Kleaf's `--config=fast` implies `local`,
which prevents Bazel from caching the main KernelBuild action. The Bazel
profile is exported to distinguish actual execution from cache reuse.
Before compilation, `stabilize_inputs.py` excludes nested Git metadata from
the source filegroup and resolves NoMount/BBG version metadata from their
locked checkouts. Their Git repositories remain available for provenance;
clone timestamps and reflogs must not invalidate the kernel action. The
resolved metadata and modified-file hashes are recorded in
`stable-inputs.json`. A restored Actions cache alone is not proof of a main
KernelBuild hit; compare the profile and build duration on the same recipe.
An empty first cache cannot speed up the first build, and a changed kernel
configuration may invalidate the whole kernel action. No CCTV ccache archive,
entire output tree, source tree or Release bucket is imported.

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
- SUSFS rollup filtering is adapted to the pinned kernel's statistics paths.
  mmap lock/retry/iterator behavior and address-range handling must be preserved.
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
only a build dependency, not device acceptance. C2 moves the NFT generation
state into its existing `nftables_pernet` allocation, leaving `struct net`
unchanged even with NF_TABLES enabled. All eight accesses retain their original
memory ordering. The network namespace framework allocates this storage before
NFT initialization and frees it after hook teardown and the RCU grace period.
No CRC, vermagic or force-load bypass is added. Selected NFT features stay
built in; future NFT modules using generation helpers would need an explicit
review of the currently unexported `nf_tables_net_id` dependency.

This addresses the known layout cause, but the complete C2 image must still
pass the actual ROM's vendor-module checks and device testing. C1 6.12.96 has
passed a single device boot and ZRAM round-trip test; B's historical slow boot
remains an open measurement question. Do not change selected features to hide
either issue.

Re-Kernel remains a selected C3 capability. It reports events to compatible
userspace clients; it does not choose or freeze apps by itself. A third-party
freezer is optional and should be evaluated separately from kernel support.

For maintenance, update a compatible component set on an isolated branch,
including its manifest, superproject, toolchain and source timestamp. Review
the changed source contracts, replay patches, then build C1 before C2 and C3.
If testing A/B baselines separately, build A before B. Keep the
last working locks, candidate ZIP, Manager and evidence together. A ROM/vendor
update requires fresh KMI, page-size and vendor module checks. Keep new network,
compression or scheduling experiments in separate minimal changes.
