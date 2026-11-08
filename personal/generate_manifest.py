#!/usr/bin/env python3
"""Pin the complete upstream manifest to its matching superproject tree."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

p = argparse.ArgumentParser()
p.add_argument("manifest_base64", type=Path)
p.add_argument("superproject", type=Path)
a = p.parse_args()
here = Path(__file__).resolve().parent
locks = json.loads((here / "locks.json").read_text())
def git(*args):
    return subprocess.check_output(["git", "-C", str(a.superproject), *args], text=True).strip()
assert git("rev-parse", "HEAD") == locks["superproject"]
assert git("show", "HEAD:.supermanifest").split()[-1] == locks["manifest"]
tree = {}
for line in git("ls-tree", "-r", "HEAD").splitlines():
    mode, kind, rest = line.split(" ", 2)
    sha, path = rest.split("\t", 1)
    if mode == "160000" and kind == "commit":
        tree[path] = sha
root = ET.fromstring(base64.b64decode(a.manifest_base64.read_bytes()))
assert not root.findall("include")
projects = root.findall("project")
assert {p.get("path", p.get("name")) for p in projects} == set(tree)
root.find("remote").set("fetch", "https://android.googlesource.com/")
root.find("default").attrib.pop("revision", None)
root.find("superproject").set("revision", locks["superproject"])
for project in projects:
    project.set("revision", tree[project.get("path", project.get("name"))])
assert tree["common"] == locks["common"]
ET.indent(root, space="  ")
ET.ElementTree(root).write(here / "manifest.xml", encoding="UTF-8", xml_declaration=True)
print(f"Pinned {len(projects)} projects; common={tree['common']}")
