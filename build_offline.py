#!/usr/bin/env python3
"""Build a self-contained, double-clickable copy of the VCF Upgrade Planner.

Upstream (https://github.com/vmware/vcf-upgrade-planner) is designed to be served
over HTTP. Its pages fetch() their JSON data, which browsers block under file:// --
so an unzipped copy renders "No components available" and nothing else.

This script produces a copy that works by double-clicking index.html, with no web
server and no internet connection, by:

  1. Inlining each scenario page's JSON data and removing the fetch() call.
  2. Shipping the home page's compatibility data as a script instead of fetching it.
  3. Seeding the Kubernetes upgrade matrix from the copy upstream already embeds in
     each page, so the fetch() fallback for it never runs.
  4. Removing the hits.sh visitor counters and usage beacons, third-party requests
     that leak the viewer's IP and render as broken images offline.

No planning logic or content is modified.

Usage:
    python3 build_offline.py            # build dist/ and the zip
    python3 build_offline.py --no-zip   # build the folder only

To refresh after upstream changes, just run it again.
"""
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
OUT = DIST / "VCF-Upgrade-Planner"

UPSTREAM_URL = "https://github.com/vmware/vcf-upgrade-planner.git"
UPSTREAM_DIR = ROOT / "upstream"

FETCH_RE = re.compile(
    r"const\s+response\s*=\s*await\s+fetch\(\s*['\"](?P<json>[^'\"]+\.json)['\"]\s*\);"
    r"\s*\n\s*upgradeData\s*=\s*await\s+response\.json\(\);"
)
# index.html's loader for compat-data.json (the version-compatibility tables).
COMPAT_FILE = "compat-data.json"
COMPAT_FETCH_RE = re.compile(
    r"fetch\(DATA_FILE\)\s*\.then\(function\(r\)\{\s*return r\.ok \? r\.json\(\) : Promise\.reject\(r\.status\);\s*\}\)"
)
# Upstream embeds k8s-upgrade-matrix.json in every page and only fetch()es it as a
# fallback. The fallbacks are safe to leave once the embedded copy is seeded.
MATRIX_FILE = "k8s-upgrade-matrix.json"
MATRIX_BLOCK_RE = re.compile(
    r'<script type="application/json" id="matrix-data">(?P<json>.*?)</script>', re.S
)
MATRIX_FALLBACK_RE = re.compile(r"fetch\(\s*['\"]k8s-upgrade-matrix\.json['\"]\s*\)")
# A real call, not prose like "<code>fetch()</code>".
FETCH_CALL_RE = re.compile(r"\bfetch\((?!\))")

# Sidebar badge as an inline <img> (scenario pages).
COUNTER_RE = re.compile(
    r'\s*<div class="sidebar-counter">\s*<img src="https://hits\.sh/[^"]*"[^>]*/?>\s*</div>',
    re.S,
)
# Usage beacons fired on export and copy, e.g.
#   if ('https://hits.sh/...') new Image().src = 'https://hits.sh/...';
BEACON_RE = re.compile(
    r"(?:if\s*\(\s*'https://hits\.sh/[^']*'\s*\)\s*)?"
    r"new Image\(\)\.src\s*=\s*'https://hits\.sh/[^']*';"
)
# Reports the viewer's current and target VCF versions, read from localStorage:
#   <script>(function(){ var B='https://hits.sh/.../versions-r4/'; ... })();</script>
VERSION_BEACON_RE = re.compile(
    r"<script>\s*\(function\(\)\{\s*var B='https://hits\.sh/[^']*';.*?\}\)\(\);\s*</script>",
    re.S,
)
# counter.js renders the badges and defines the tracking hooks pages call into.
# Replaced with no-ops so those calls still resolve.
COUNTER_JS_STUB = """\
// Offline build: upstream's third-party visitor counter and usage tracking removed.
window.trackEvent = function () {};
window.trackSupervisorConfig = function () {};
"""

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
networking and resource requirements, and an overall workflow. A
separate planner covers vSphere Kubernetes Service (VKS) upgrades.

Plans can be exported to PDF from within the tool.


NOTE ON EXTERNAL LINKS
----------------------
The planner itself runs fully offline. Some pages link out to Broadcom
documentation and the VMware Interoperability Matrix, and a few
embedded documentation topics show images hosted online. Those need an
internet connection and will not open on an isolated network. The
planning tool works regardless.


SOURCE
------
This is a repackaged copy of the open-source VMware tool at:
https://github.com/vmware/vcf-upgrade-planner

It has been modified only to run offline: the planning data is
embedded directly in the pages, and third-party visitor-tracking
requests have been removed. No planning logic or content has been
changed.
"""


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
        # A depth-1 clone can't fast-forward: the new commit's parent isn't in the
        # local history, so `git pull --ff-only` refuses. upstream/ is a generated
        # mirror, so fetch the latest tip and reset onto it instead.
        for cmd in (
            ["fetch", "--depth", "1", "origin", "HEAD"],
            ["reset", "--hard", "FETCH_HEAD"],
        ):
            r = subprocess.run(
                ["git", "-C", str(UPSTREAM_DIR), *cmd], capture_output=True, text=True
            )
            if r.returncode != 0:
                # Building from a stale copy would silently ship outdated plans.
                sys.exit(
                    f"ERROR: could not refresh upstream (git {cmd[0]}).\n{r.stderr.strip()}\n"
                    f"Delete {UPSTREAM_DIR} to re-clone, or check network access."
                )
    else:
        print(f"Cloning upstream -> {UPSTREAM_DIR}")
        r = subprocess.run(
            ["git", "clone", "--depth", "1", UPSTREAM_URL, str(UPSTREAM_DIR)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            sys.exit(f"ERROR: could not clone upstream.\n{r.stderr.strip()}")

    head = subprocess.run(
        ["git", "-C", str(UPSTREAM_DIR), "log", "-1", "--format=%h %cs %s"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    print(f"  upstream at {head}")
    return UPSTREAM_DIR


def load_json(path: Path, failures: list[str], who: str):
    if not path.exists():
        failures.append(f"{who}: missing data file {path.name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        failures.append(f"{who}: {path.name} is not valid JSON ({e})")
        return None


def main() -> None:
    make_zip = "--no-zip" not in sys.argv

    upstream = resolve_upstream()
    src = upstream / "docs"
    if not src.is_dir():
        sys.exit(f"ERROR: {src} not found -- upstream layout changed?")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    print("\nCopying scripts:")
    for js in sorted(src.glob("*.js")):
        if js.name == "counter.js":
            (OUT / js.name).write_text(COUNTER_JS_STUB, encoding="utf-8")
            print(f"  {js.name:<74} replaced with no-op stub")
        else:
            shutil.copy2(js, OUT / js.name)
            print(f"  {js.name}")

    failures: list[str] = []
    matrix = load_json(src / MATRIX_FILE, failures, "build")

    print("\nRewriting pages:")
    inlined = 0
    for html in sorted(src.glob("*.html")):
        text = html.read_text(encoding="utf-8")
        name = html.name
        notes: list[str] = []
        if "</head>" not in text:
            failures.append(f"{name}: no </head> to inject into")
            continue

        m = FETCH_RE.search(text)
        if m:
            payload = load_json(src / m.group("json"), failures, name)
            if payload is None:
                continue
            blob = json.dumps(payload, separators=(",", ":"))
            # Neutralise sequences that would terminate the <script> early.
            blob = blob.replace("</", "<\\/").replace("<!--", "<\\!--")
            text = FETCH_RE.sub("upgradeData = window.__UPGRADE_DATA__;", text)
            text = text.replace(
                "</head>", f"<script>window.__UPGRADE_DATA__ = {blob};</script>\n</head>", 1
            )
            notes.append(f"inlined {m.group('json')}")
            inlined += 1

        text, n = COMPAT_FETCH_RE.subn("Promise.resolve(window.__COMPAT_DATA__)", text)
        if n:
            compat = load_json(src / COMPAT_FILE, failures, name)
            if compat is None:
                continue
            # A separate script, not inlined: it's 4 MB and shared by nothing else,
            # and <script src> loads fine under file://.
            js_name = COMPAT_FILE.replace(".json", ".js")
            (OUT / js_name).write_text(
                "window.__COMPAT_DATA__ = "
                + json.dumps(compat, separators=(",", ":"))
                + ";\n",
                encoding="utf-8",
            )
            text = text.replace("</head>", f'<script src="{js_name}"></script>\n</head>', 1)
            notes.append(f"{COMPAT_FILE} -> {js_name}")

        block = MATRIX_BLOCK_RE.search(text)
        if block:
            try:
                embedded = json.loads(block.group("json"))
            except json.JSONDecodeError:
                embedded = None
            if embedded != matrix:
                # Upstream re-embeds by hand (embed_vks_matrix.py); catch a missed run.
                failures.append(f"{name}: embedded {MATRIX_FILE} is stale or invalid")
                continue
            seed = (
                "<script>window._k8sMatrix = window._k8sMatrix || "
                "JSON.parse(document.getElementById('matrix-data').textContent);</script>"
            )
            text = text[: block.end()] + seed + text[block.end() :]
            notes.append("seeded k8s matrix")

        # Every fetch() left must be a matrix fallback that the seed makes unreachable.
        stray = FETCH_CALL_RE.findall(MATRIX_FALLBACK_RE.sub("", text) if block else text)
        if stray:
            failures.append(f"{name}: has fetch() but not a known pattern -- upstream changed")
            continue

        text, n_cnt = COUNTER_RE.subn("", text)
        text, n_bcn = BEACON_RE.subn("", text)
        text, n_ver = VERSION_BEACON_RE.subn("", text)
        if n_cnt or n_bcn or n_ver:
            notes.append(f"removed {n_cnt + n_bcn + n_ver} tracker(s)")

        (OUT / name).write_text(text, encoding="utf-8")
        print(f"  {name:<74} {', '.join(notes) or 'copied as-is'}")

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        sys.exit(1)

    (OUT / "README.txt").write_text(README, encoding="utf-8")
    shutil.copy2(upstream / "LICENSE", OUT / "LICENSE")

    for junk in OUT.rglob(".DS_Store"):
        junk.unlink()

    # Fail loudly if any tracker or external asset reference survived.
    leaked = []
    for p in sorted(OUT.glob("*.html")) + sorted(OUT.glob("*.js")):
        t = p.read_text(encoding="utf-8")
        if "hits.sh" in t:
            leaked.append(f"{p.name} (hits.sh tracker)")
        if re.search(r'<(script|link)\b[^>]*\b(src|href)="https?://', t):
            leaked.append(f"{p.name} (external script/stylesheet)")
    if leaked:
        sys.exit("ERROR: external references still present in:\n  " + "\n  ".join(leaked))

    print(f"\nInlined {inlined} scenario pages. No trackers or external scripts remain.")

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
