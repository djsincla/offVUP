# offVUP — offline VCF Upgrade Planner

Builds a **self-contained, double-clickable** copy of VMware's
[VCF Upgrade Planner](https://github.com/vmware/vcf-upgrade-planner) for customers
who can't reach GitHub or the internet.

## Build

```bash
python3 build_offline.py
```

Produces `dist/VCF-Upgrade-Planner.zip` (~3.6 MB). Needs Python 3 and `git`.
Upstream is cloned into `upstream/` automatically on first run and refreshed after.

To rebuild after VMware updates the planner, just run it again.

## Deliver

Send the zip. The customer unzips it, double-clicks `index.html`, and it opens in
their browser. No web server, no internet, no admin rights. Windows, Mac, Linux.

## Why this exists

Upstream is built to be *served over HTTP*. Its scenario pages `fetch()` their JSON
data, which browsers block under `file://` — so an unzipped copy of upstream renders
**"No components available"** and nothing else. Verified in headless Chrome.

The build makes three changes, and nothing else:

| Change | Reason |
|---|---|
| Inline each scenario page's JSON, drop the `fetch()` | The actual `file://` fix |
| Vendor `mermaid.min.js` locally | Upstream loads it from a CDN; workflow diagrams would break offline |
| Remove the `hits.sh` counter image | Third-party beacon: leaks viewer IP + user-agent to a personal server in South Korea, and renders as a broken image offline |

No planning logic or content is touched.

The script fails loudly rather than shipping something broken — if upstream changes
its `fetch()` pattern, or any external asset reference survives, the build aborts.

## Known limitation

The planner runs fully offline, but some pages link out to Broadcom techdocs and the
VMware Interoperability Matrix. Those links need internet and won't open on an
isolated network. Called out in the README the customer receives.

## Licensing

Upstream is CA, Inc.-licensed and explicitly permits modified redistribution "in
connection with CA, Inc. products", provided the copyright notice ships with all
copies. The build copies upstream's `LICENSE` into the zip and generates
`THIRD-PARTY-NOTICES.txt` covering the vendored mermaid (MIT).

`upstream/`, `vendor/`, and `dist/` are generated and git-ignored.
