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

PDFs use a local, rule-based semantic candidate pass over reconstructed page text.
It identifies numbered theorem/lemma/proposition/corollary/conjecture/definition
headings, associates nearby proof text, and resolves explicit statement references.
Every candidate and reference carries exact reconstructed-page character spans and
excerpt hashes. The inspector exposes statement/proof text, uncertainty and reference
rationales. Mention edges and candidate dependency cues are distinct; neither is a
verified derivation. Ambiguous/missing targets and truncation are reported for review.

This is not a general mathematical reasoner or a model-generated summary. Layout,
unnumbered claims, unusual headings, equations, implicit arguments and cross-document
references can be missed or misread. No probability of mathematical truth is assigned.
The existing formal acceptance pipeline is unchanged; candidates never become accepted
claims merely by import. Scanned/image-only PDFs need OCR
outside the Studio. Multi-file TeX projects should use the existing CLI. Uploads
are limited to 4,000,000 bytes per PDF/TeX file and 8 MiB per JSON map,
250 pages per PDF, ten files per UI batch, and one active server
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

## Newton, Einstein and entropy-gravity boundary lab

Use the **Gravity boundary lab** button below the workspace to load a curated
transition map, then click **Start boundary analysis**. Actionable stages focus
the graph on assumptions, explicit gaps, a candidate GR extension and limit recovery.
The extension into entropic/emergent gravity is labelled as a research frontier,
not an established successor. Jacobson and Verlinde approaches are kept distinct.
Each stage provides a boundary question, evidence, an analysis action and an
interpretation. **Next analysis step** advances; **Show full map** clears focus.
It distinguishes special relativity from general relativity,
exposes the weak-field/slow-motion assumptions of the Newtonian limit and links
claims to reference sources. See [the case notes](GRAVITY_TRANSITION.md).
This is a teaching example, not an automatically extracted PDF or a verified proof.
