# Research Studio (local web interface)

The Studio is an additive UX for the public toolkit, not a replacement for the
campaign CLI, verifier or evidence review. It never grants proof authority.

## Start

```sh
python -m pip install -e '.[paper]'
python -m proofmap.studio --port 8765
```

Open `http://127.0.0.1:8765`. The server binds only to loopback, not your LAN.
Do not expose it through a tunnel or public reverse proxy. Public multi-user
hosting, authentication and persistent server-side libraries are not provided.

## Workflows

- Explore the bundled illustrative strong/weak-interface map. Orbit/zoom the
  sphere, switch to the atlas, filter layers or search claims. The claim list
  provides keyboard access to the same inspector as the canvas.
- Drag and drop a **standalone TeX**, **text-bearing PDF**, or schema-valid
  **ProofMap JSON** file. The source library also offers a file chooser.
- Paper intake uses the existing bounded `paper.ci` pipeline with extractor
  `none`. It reports source assertions, lexical dependencies, parser diagnostics,
  source anchors and pipeline checks. It does not call a model, run an authorized
  Lean verifier, approve fidelity or certify proof.
- JSON maps use existing schema validation, geometric diagnostics and surface
  layout. Authored statuses, reachability and colors are not accepted evidence.
- Inspect diagnostics and provenance in the Analysis desk. Export the current
  analysis as JSON or save the rendered boundary view as PNG.

## Scope and privacy

Paper nodes are a **source-dependency layout**, not measured proof-boundary
geometry. No unsupported mathematical certainty or uncertainty score is invented.
A map's authored uncertainty is displayed only when supplied. Absence of findings
is not correctness. The reference map is labelled as a demonstration.

PDF extraction requires the pinned paper extra. Scanned/image-only PDFs need OCR
outside the Studio. Multi-file TeX projects should use the existing CLI. Uploads
are limited to 8 MiB per file, ten files per UI batch, and one active server
analysis. Maps are capped at 2,000 nodes/8,000 edges; the graph and claim index show
the first 500 matches, with search available to narrow the set. The analysis
worker has a 90-second deadline. Missing dependencies or failed parsing remain
visible errors, never a fabricated successful result.

Uploaded bytes are processed in a temporary local directory and removed after
analysis. Session results live only in browser memory and clear on reload. Export
before leaving if needed. No analytics, CDN assets, model requests or remote
paper uploads are used. Exported analysis JSON is a report, not a ProofMap input
or portable campaign dossier; use the existing campaign dossier workflow for
persistent research history. Original uploaded files are not modified.

Loopback Host/Origin validation, a same-origin custom request header, content and
size checks, a static-file allowlist, security response headers and a single
analysis slot limit the local service surface. These controls are not a public
hosting security qualification.

## Validation

```sh
python -m pytest tests/test_studio.py -q
python -m playwright install chromium
python scripts/verify_studio_browser.py
```

The explicit Chromium smoke checks demo rendering, filters, projection, claim
inspection, JSON download, actual TeX upload, drag-and-drop, malformed-input
recovery, small-screen overflow and reload clearing. Screenshots and the local
result are saved under ignored `.work/studio-qa/`. The test uses its own ephemeral
loopback port. Backend tests additionally cover real text-PDF intake, schema
validation, upload limits and origin/host rejection.

These checks do not establish full alpha/beta release readiness. The repository's
existing aggregate CI, platform, Lean and container qualification gates still
apply to any release candidate.
