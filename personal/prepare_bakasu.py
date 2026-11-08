#!/usr/bin/env python3
"""Wire the R22 SUSFS API into the pinned native BakaSU implementation."""
import argparse
import json
from pathlib import Path
import subprocess


def prepare(root, locks, check_only=False):
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    assert head == locks["components"]["BakaSU"]["commit"], head
    assert locks["bakasu_codegen_guard_upstream"] == head
    kernel = root / "kernel"
    kbuild = (kernel / "Kbuild").read_text()
    generator = "include $(KSU_SRC)/tools/code_generation/code_generation.mk"
    assert kbuild.count(generator) == 1
    assert "ifneq ($(CONFIG_KSU),)\n" + generator + "\nendif" in kbuild
    assert not (kernel / "bakasu_susfs_compat.c").exists()

    dispatch = kernel / "supercall/dispatch.c"
    observer = kernel / "manager/pkg_observer.c"
    source = dispatch.read_text()
    events = observer.read_text()
    header = "#include <linux/susfs_def.h>"
    command = "    case CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING: {"
    watch_header = '#include "manager/throne_tracker.h"'
    track = "    track_throne(TRACK_THRONE_FORCE_SYNCHRONOUS);"
    if check_only:
        assert source.count("case CMD_SUSFS_SET_PRIORITY_UID_FILTER:") == 1
        assert "susfs_set_priority_uid_filter(arg);" in source
        assert events.count("susfs_parse_priority_app_strings();") == 1
        # Only the deferred task-work callback may start the worker. The
        # allocation-failure fallback runs inside fsnotify/rename locks.
        deferred, fallback = events.split("static void ksu_defer_track_throne", 1)
        assert "susfs_parse_priority_app_strings();" in deferred
        assert "susfs_parse_priority_app_strings();" not in fallback
        assert "#include <linux/susfs.h>" in source and "#include <linux/susfs.h>" in events
        return
    assert "CMD_SUSFS_SET_PRIORITY_UID_FILTER" not in source
    assert "susfs_parse_priority_app_strings" not in events
    assert source.count(header) == source.count(command) == 1
    assert events.count(watch_header) == 1 and events.count(track) == 2
    source = source.replace(header, header + "\n#include <linux/susfs.h>", 1)
    source = source.replace(command, """    case CMD_SUSFS_SET_PRIORITY_UID_FILTER: {
        susfs_set_priority_uid_filter(arg);
        return 0;
    }
""" + command, 1)
    events = events.replace(watch_header, watch_header + """
#ifdef CONFIG_KSU_SUSFS
#include <linux/susfs.h>
#endif
""", 1)
    events = events.replace(track, track + """
#ifdef CONFIG_KSU_SUSFS
    susfs_parse_priority_app_strings();
#endif
""", 1)
    # Validate every anchor before changing either file.
    dispatch.write_text(source)
    observer.write_text(events)
    prepare(root, locks, check_only=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bakasu", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    locks = json.loads((Path(__file__).parent / "locks.json").read_text())
    prepare(args.bakasu, locks, args.check_only)
    print("PASS: native codegen guard and R22 SUSFS command/package observer contracts")
