# offVUP — offline VCF Upgrade Planner

Builds a **self-contained, double-clickable** copy of VMware's
[VCF Upgrade Planner](https://github.com/vmware/vcf-upgrade-planner) for customers
who can't reach GitHub or the internet.

## Build

```bash
python3 build_offline.py
```

Produces `dist/VCF-Upgrade-Planner.zip` (~5 MB). Needs Python 3 and `git`.
Upstream is cloned into `upstream/` automatically on first run and refreshed to the
latest commit after. If the refresh fails, the build stops rather than packaging a stale copy.

To rebuild after VMware updates the planner, just run it again.

## Deliver

Send the zip. The customer unzips it, double-clicks `index.html`, and it opens in
their browser. No web server, no internet, no admin rights. Windows, Mac, Linux.

## Why this exists

Upstream is built to be *served over HTTP*. Its pages `fetch()` their JSON data, which browsers block under `file://` — so an unzipped copy of upstream renders
**"No components available"** and nothing else. Verified in headless Chrome.

The build makes these changes, and nothing else:

| Change | Reason |
|---|---|
| Inline each scenario page's JSON, drop the `fetch()` | The actual `file://` fix |
| Ship `compat-data.json` as `compat-data.js`, loaded by `<script>` | Same fix for the home page's version-compatibility data (4 MB) |
| Seed the Kubernetes upgrade matrix from the copy upstream embeds in each page | Upstream's `fetch()` fallback for it would otherwise run, and fail, first. The build aborts if an embedded copy is stale |
| Replace `counter.js` with no-op stubs, strip inline `hits.sh` beacons | Third-party tracking to a personal server in South Korea: page visits, every export/copy, and the customer's current and target VCF versions. Renders as broken images offline |

No planning logic or content is touched.

The script fails loudly rather than shipping something broken — if upstream adds a
`fetch()` it doesn't recognise, or any tracker or external script survives, the build aborts.

## Known limitation

The planner runs fully offline, but some pages link out to Broadcom techdocs and the
VMware Interoperability Matrix, and a few embedded doc topics show images hosted
online. Those need internet and won't load on an isolated network. Called out in the
README the customer receives.

On the 9.0 → 9.1 pages, upstream rewrites the address bar to a filename that doesn't
exist when a target version is picked. Browsers refuse this under `file://`, and
upstream catches the error and logs it to the console. Harmless, and left alone.

## Licensing

Upstream is CA, Inc.-licensed and explicitly permits modified redistribution "in
connection with CA, Inc. products", provided the copyright notice ships with all
copies. The build copies upstream's `LICENSE` into the zip. (Upstream dropped mermaid, so
there is no longer any vendored third-party code or `THIRD-PARTY-NOTICES.txt`.)

`upstream/` and `dist/` are generated and git-ignored.
