#!/usr/bin/env python3
"""Build a self-contained, double-clickable copy of the VCF Upgrade Planner.

Upstream (https://github.com/vmware/vcf-upgrade-planner) is designed to be served
over HTTP. Its scenario pages fetch() their JSON data, which browsers block under
file:// -- so an unzipped copy renders "No components available" and nothing else.

This script produces a copy that works by double-clicking index.html, with no web
server and no internet connection, by:

  1. Inlining each scenario page's JSON data and removing the fetch() call.
  2. Vendoring the mermaid diagram library, which upstream loads from a CDN.
  3. Removing the hits.sh visitor-counter image, a third-party beacon that would
     both leak the viewer's IP and render as a broken image offline.

No planning logic or content is modified.

Usage:
    python3 build_offline.py            # build dist/ and the zip
    python3 build_offline.py --no-zip   # build the folder only

To refresh after upstream changes:  git pull && python3 build_offline.py
"""
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
OUT = DIST / "VCF-Upgrade-Planner"
VENDOR = ROOT / "vendor"

UPSTREAM_URL = "https://github.com/vmware/vcf-upgrade-planner.git"
UPSTREAM_DIR = ROOT / "upstream"

# Pinned for reproducible builds. Upstream floats on mermaid@11.
MERMAID_VERSION = "11.16.0"
MERMAID_URL = f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js"
MERMAID_LICENSE_URL = "https://raw.githubusercontent.com/mermaid-js/mermaid/develop/LICENSE"

FETCH_RE = re.compile(
    r"const\s+response\s*=\s*await\s+fetch\(\s*['\"](?P<json>[^'\"]+\.json)['\"]\s*\);"
    r"\s*\n\s*upgradeData\s*=\s*await\s+response\.json\(\);"
)
MERMAID_RE = re.compile(r'src="https://cdn\.jsdelivr\.net/npm/mermaid@11/dist/mermaid\.min\.js"')
COUNTER_RE = re.compile(
    r'\s*<div class="sidebar-counter">\s*<img src="https://hits\.sh/[^"]*"[^>]*/?>\s*</div>',
    re.S,
)

README = """VCF Upgrade Planning Tool - Offline Copy
========================================

HOW TO USE
----------
1. Unzip this folder anywhere (Desktop is fine).
2. Double-click "index.html".
3. It opens in your web browser. That's it.

There is nothing to install. No web server, no internet connection,
and no admin rights are required. Works on Windows, Mac, and Linux.

IMPORTANT: Keep all the files in this folder together. Moving
"index.html" out on its own will stop it working.


WHAT IT DOES
------------
Interactive step-by-step planning for VMware Cloud Foundation (VCF)
upgrades to 9.1. Pick your scenario from the start page, answer the
questions about your environment, and it produces your upgrade phases,
networking and resource requirements, and an overall workflow.

Plans can be exported to PDF from within the tool.


NOTE ON EXTERNAL LINKS
----------------------
The planner itself runs fully offline. Some pages link out to Broadcom
documentation and the VMware Interoperability Matrix. Those links need
an internet connection, and will not open on an isolated network. The
planning tool works regardless.


SOURCE
------
This is a repackaged copy of the open-source VMware tool at:
https://github.com/vmware/vcf-upgrade-planner

It has been modified only to run offline: the scenario data is embedded
directly in the pages, the diagram library is included locally, and a
third-party visitor-tracking image has been removed. No planning logic
or content has been changed.
"""


def fetch_cached(url: str, dest: Path) -> Path:
    """Download url to dest unless already cached."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cached   {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  fetching {dest.name} <- {url}")
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    if not data:
        sys.exit(f"ERROR: empty download from {url}")
    dest.write_bytes(data)
    return dest


def resolve_upstream() -> Path:
    """Return the directory holding upstream's docs/ and LICENSE.

    Works either inside a clone of vcf-upgrade-planner, or standalone -- in which
    case upstream is cloned into ./upstream and refreshed on later runs.
    """
    if (ROOT / "docs").is_dir():
        print(f"Using upstream in place: {ROOT}")
        return ROOT

    if (UPSTREAM_DIR / "docs").is_dir():
        print(f"Refreshing upstream clone: {UPSTREAM_DIR}")
        r = subprocess.run(
            ["git", "-C", str(UPSTREAM_DIR), "pull", "--depth", "1", "--ff-only"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"  WARNING: pull failed, using existing copy ({r.stderr.strip().splitlines()[-1:]})")
        return UPSTREAM_DIR

    print(f"Cloning upstream -> {UPSTREAM_DIR}")
    r = subprocess.run(
        ["git", "clone", "--depth", "1", UPSTREAM_URL, str(UPSTREAM_DIR)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        sys.exit(f"ERROR: could not clone upstream.\n{r.stderr.strip()}")
    return UPSTREAM_DIR


def main() -> None:
    make_zip = "--no-zip" not in sys.argv

    upstream = resolve_upstream()
    src = upstream / "docs"
    if not src.is_dir():
        sys.exit(f"ERROR: {src} not found -- upstream layout changed?")

    print("\nVendoring third-party assets:")
    mermaid = fetch_cached(MERMAID_URL, VENDOR / "mermaid.min.js")
    mermaid_license = fetch_cached(MERMAID_LICENSE_URL, VENDOR / "mermaid-LICENSE")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    shutil.copy2(mermaid, OUT / "mermaid.min.js")
    shutil.copy2(src / "docs_inline.js", OUT / "docs_inline.js")

    print("\nRewriting pages:")
    failures: list[str] = []
    inlined = 0
    for html in sorted(src.glob("*.html")):
        text = html.read_text(encoding="utf-8")
        name = html.name
        notes: list[str] = []

        m = FETCH_RE.search(text)
        if m:
            data_file = src / m.group("json")
            if not data_file.exists():
                failures.append(f"{name}: missing data file {m.group('json')}")
                continue
            try:
                payload = json.loads(data_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                failures.append(f"{name}: {m.group('json')} is not valid JSON ({e})")
                continue
            blob = json.dumps(payload, separators=(",", ":"))
            # Neutralise sequences that would terminate the <script> early.
            blob = blob.replace("</", "<\\/").replace("<!--", "<\\!--")
            if "</head>" not in text:
                failures.append(f"{name}: no </head> to inject into")
                continue
            text = FETCH_RE.sub("upgradeData = window.__UPGRADE_DATA__;", text)
            text = text.replace(
                "</head>", f"<script>window.__UPGRADE_DATA__ = {blob};</script>\n</head>", 1
            )
            notes.append(f"inlined {m.group('json')}")
            inlined += 1
        elif "fetch(" in text:
            failures.append(f"{name}: has fetch() but not the expected pattern -- upstream changed")
            continue

        text, n_merm = MERMAID_RE.subn('src="mermaid.min.js"', text)
        if n_merm:
            notes.append("vendored mermaid")
        text, n_cnt = COUNTER_RE.subn("", text)
        if n_cnt:
            notes.append("removed tracker")

        (OUT / name).write_text(text, encoding="utf-8")
        print(f"  {name:<74} {', '.join(notes) or 'copied as-is'}")

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        sys.exit(1)

    (OUT / "README.txt").write_text(README, encoding="utf-8")
    shutil.copy2(upstream / "LICENSE", OUT / "LICENSE")
    (OUT / "THIRD-PARTY-NOTICES.txt").write_text(
        "THIRD-PARTY NOTICES\n"
        "===================\n\n"
        "This package includes the following third-party component:\n\n"
        f"mermaid v{MERMAID_VERSION} (mermaid.min.js)\n"
        "https://github.com/mermaid-js/mermaid\n"
        "Used to render the upgrade workflow diagrams. Included locally so the\n"
        "tool works without an internet connection.\n\n"
        + mermaid_license.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    for junk in OUT.rglob(".DS_Store"):
        junk.unlink()

    # Fail loudly if any external asset reference survived.
    leaked = [
        p.name
        for p in OUT.glob("*.html")
        if re.search(r'(src|href)="https?://[^"]*\.(js|css|svg|png)', p.read_text(encoding="utf-8"))
    ]
    if leaked:
        sys.exit(f"ERROR: external asset refs still present in: {', '.join(leaked)}")

    print(f"\nInlined {inlined} scenario pages. No external asset references remain.")

    if make_zip:
        zip_path = DIST / "VCF-Upgrade-Planner.zip"
        zip_path.unlink(missing_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(OUT.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(DIST))
        mb = zip_path.stat().st_size / 1_048_576
        print(f"Built -> {zip_path} ({mb:.1f} MB)")
    else:
        print(f"Built -> {OUT}")


if __name__ == "__main__":
    main()
