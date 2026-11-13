"use strict";
const $ = (id) => document.getElementById(id);
const colors = {
  CORE: "#80dccb",
  INTERIOR: "#8ba7e8",
  BOUNDARY: "#e9b775",
  EXTERIOR: "#cd8eab",
};
const state = {
  data: null,
  sessions: [],
  current: -1,
  selected: null,
  query: "",
  layers: new Set(Object.keys(colors)),
  projection: "sphere",
  yaw: 0.45,
  pitch: 0.18,
  zoom: 1,
  rotate: false,
  points: [],
  busy: false,
  stage: -1,
  focusIds: null,
};
const canvas = $("map-canvas"),
  ctx = canvas.getContext("2d");
let width = 0,
  height = 0,
  lastFrame = 0,
  dirty = true,
  drag = null,
  dragDepth = 0;
const reducedMotion = window.matchMedia(
  "(prefers-reduced-motion: reduce)",
).matches;
function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = String(text);
  if (cls) n.className = cls;
  return n;
}
function setStatus(message, error = false) {
  $("status").textContent = message;
  $("status").className = "status" + (error ? " error" : "");
}
function clearStatus() {
  $("status").className = "status hidden";
}
function view(name) {
  document
    .querySelectorAll(".view")
    .forEach((n) => n.classList.toggle("active", n.id === name + "-view"));
  document.querySelectorAll(".nav").forEach((n) => {
    n.classList.toggle("active", n.dataset.view === name);
    if (n.dataset.view === name) n.setAttribute("aria-current", "page");
    else n.removeAttribute("aria-current");
  });
  $("view-name").textContent = {
    map: "Boundary explorer",
    papers: "Source library",
    analysis: "Analysis desk",
  }[name];
  resize();
}
document
  .querySelectorAll(".nav")
  .forEach((n) => n.addEventListener("click", () => view(n.dataset.view)));
function human(value) {
  return String(value ?? "Not available").replaceAll("_", " ");
}
function count(metric, fallback) {
  const v = state.data?.metrics?.[metric];
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
}
function normalizedNodes(data) {
  return (data.nodes || []).map((n) => ({
    ...n,
    id: String(n.id),
    label: String(n.label || n.id),
    layer: colors[n.layer] ? n.layer : "BOUNDARY",
  }));
}
function selectData(data, index) {
  state.data = {
    ...data,
    nodes: normalizedNodes(data),
    edges: data.edges || [],
  };
  state.current = index;
  state.stage = -1;
  state.focusIds = null;
  state.selected = null;
  state.query = "";
  $("search").value = "";
  state.yaw = 0.45;
  state.pitch = 0.18;
  state.zoom = 1;
  render();
}
function render() {
  if (!state.data) return;
  const d = state.data,
    paper = d.mode === "paper";
  const semantic = !!d.semantic_extraction;
  $("nodes-label").textContent = semantic
    ? "Extracted candidates"
    : "Mapped claims";
  $("edges-label").textContent = semantic
    ? "Referenced relationships"
    : "Dependencies";
  $("map-title").textContent = d.title;
  $("mode-tag").textContent = human(d.mode || "analysis").toUpperCase();
  $("metric-nodes").textContent = d.nodes.length.toLocaleString();
  $("metric-edges").textContent = d.edges.length.toLocaleString();
  $("metric-boundary").textContent = paper
    ? count("assertion_count", d.nodes.length)
    : count(
        "boundary_count",
        d.nodes.filter((n) => n.layer === "BOUNDARY").length,
      );
  $("boundary-label").textContent = paper
    ? semantic
      ? "Review required"
      : "Source assertions"
    : "Boundary nodes";
  $("boundary-detail").textContent = paper
    ? "Not independently verified"
    : "At the edge of the map";
  $("metric-gaps").textContent = paper
    ? count("accepted_claims", 0)
    : count(
        "gap_count",
        d.nodes.filter((n) => ["GAP", "BLOCKED"].includes(n.status)).length,
      );
  $("last-label").textContent = paper
    ? "Accepted claims"
    : d.boundary_walkthrough?.length
      ? "Authored gaps"
      : "Open gaps";
  $("last-detail").textContent = paper
    ? "Import does not certify proof"
    : "Require further investigation";
  $("graph-caption").textContent = paper
    ? semantic
      ? "Semantic candidate layout / source-grounded, unverified"
      : "Source dependency layout · unverified assertions"
    : "Heuristic geometry · not a proof verdict";
  renderWalkthrough();
  renderSessions();
  renderClaims();
  renderInspector();
  renderFindings();
  dirty = true;
}
function renderWalkthrough() {
  const panel = $("boundary-lab"),
    stages = state.data?.boundary_walkthrough || [];
  panel.replaceChildren();
  panel.classList.toggle("hidden", !stages.length);
  if (!stages.length) return;
  panel.append(
    el("span", "BOUNDARY ANALYSIS LAB / CURATED CASE", "eyebrow"),
    el("h2", "Find the gap. Test the bridge. Recover the limit."),
  );
  panel.append(
    el(
      "p",
      "Use the graph to inspect where Newtonian assumptions stop explaining the evidence, then evaluate Einstein's framework and the separate entropic/emergent-gravity research frontier. This walkthrough does not derive theories automatically.",
      "muted",
    ),
  );
  const steps = el("div", undefined, "walkthrough-steps");
  stages.forEach((stage, index) => {
    const button = el(
      "button",
      `${index + 1}. ${stage.title.replace(/^\d+\.\s*/, "")}`,
      state.stage === index ? "selected" : "",
    );
    button.setAttribute("aria-pressed", String(state.stage === index));
    button.onclick = () => focusStage(index);
    steps.append(button);
  });
  const all = el("button", "Show full map");
  all.onclick = () => focusStage(-1);
  steps.append(all);
  panel.append(steps);
  if (state.stage >= 0) {
    const stage = stages[state.stage],
      content = el("div", undefined, "walkthrough-detail");
    content.append(el("h3", stage.title), el("p", stage.detail));
    [
      ["Boundary question", stage.question],
      ["Evidence to inspect", stage.evidence],
      ["Analysis action", stage.action],
      ["Interpretation", stage.outcome],
    ].forEach(([label, value]) => {
      if (value) {
        const row = el("div");
        row.append(
          el("h4", label),
          el("p", Array.isArray(value) ? value.join("; ") : value),
        );
        content.append(row);
      }
    });
    const focused = state.data.nodes.filter((n) =>
      stage.node_ids.includes(n.id),
    );
    const focusedIds = new Set(focused.map((n) => n.id));
    const focusedEdges = state.data.edges.filter(
      (e) => focusedIds.has(e.source) && focusedIds.has(e.target),
    );
    const gapCount = focused.filter(
      (n) => n.kind === "GAP" || n.status === "GAP",
    ).length;
    const computed = el("div", undefined, "walkthrough-computed");
    computed.append(
      el("h4", "Computed from this graph focus"),
      el(
        "p",
        `${focused.length} nodes · ${focusedEdges.length} internal relationships · ${gapCount} authored gap markers. These counts describe the curated graph, not proof completeness.`,
      ),
    );
    const diagnostics = (state.data.findings || []).filter((f) =>
      f.nodes?.some((id) => focusedIds.has(id)),
    );
    diagnostics
      .slice(0, 3)
      .forEach((f) =>
        computed.append(el("p", `${f.title}: ${f.detail}`, "muted")),
      );
    content.append(computed);
    const next = el(
      "button",
      state.stage === stages.length - 1
        ? "Return to full map"
        : "Next analysis step →",
    );
    next.onclick = () =>
      focusStage(state.stage === stages.length - 1 ? -1 : state.stage + 1);
    content.append(next);
    panel.append(content);
  } else {
    const start = el("button", "Start boundary analysis →");
    start.onclick = () => focusStage(0);
    panel.append(start);
  }
}
function focusStage(index) {
  state.stage = index;
  const stage = state.data.boundary_walkthrough[index];
  state.focusIds = stage ? new Set(stage.node_ids) : null;
  state.query = "";
  $("search").value = "";
  state.layers = new Set(Object.keys(colors));
  document
    .querySelectorAll(".legend input")
    .forEach((input) => (input.checked = true));
  state.selected = stage?.node_ids[0] || null;
  state.zoom = 1;
  renderWalkthrough();
  renderClaims();
  renderInspector();
  dirty = true;
}
function renderSessions() {
  const list = $("session-list");
  list.replaceChildren();
  state.sessions.forEach((s, i) => {
    const b = el(
      "button",
      s.title,
      "session-button" + (i === state.current ? " active" : ""),
    );
    b.title = s.title;
    b.addEventListener("click", () => {
      selectData(s.data, i);
      view("map");
    });
    list.append(b);
  });
  if (!state.sessions.length)
    list.append(el("p", "No imported sources yet.", "muted"));
  $("paper-count").textContent = state.sessions.length;
  const library = $("library-list");
  library.replaceChildren();
  state.sessions.forEach((s, i) => {
    const row = el("div", undefined, "library-entry"),
      body = el("div");
    body.append(
      el("strong", s.title),
      el(
        "small",
        `${s.data.nodes.length} claims · ${s.data.edges.length} links · ${s.at}`,
      ),
    );
    const b = el("button", "Explore ↗");
    b.addEventListener("click", () => {
      selectData(s.data, i);
      view("map");
    });
    row.append(body, b);
    library.append(row);
  });
  if (!state.sessions.length)
    library.append(
      el(
        "p",
        "Your imported analyses will appear here. Start with a paper or explore the bundled reference map.",
        "library-footer",
      ),
    );
}
function visibleNodes() {
  return (state.data?.nodes || []).filter(
    (n) =>
      state.layers.has(n.layer) &&
      (!state.focusIds || state.focusIds.has(n.id)) &&
      (!state.query ||
        (n.label + " " + n.statement + " " + n.id)
          .toLowerCase()
          .includes(state.query)),
  );
}
function renderClaims() {
  const list = $("claim-list");
  list.replaceChildren();
  const nodes = visibleNodes();
  $("visible-count").textContent = `${nodes.length} visible`;
  nodes.slice(0, 500).forEach((n) => {
    const b = el(
      "button",
      undefined,
      "claim-item" + (state.selected === n.id ? " selected" : ""),
    );
    const dot = el("i");
    dot.style.background = colors[n.layer];
    b.append(
      dot,
      el("span", n.label, "claim-label"),
      el("span", human(n.status), "claim-state"),
      el("span", "↗", "arrow"),
    );
    b.setAttribute("aria-label", `Inspect ${n.label}`);
    b.addEventListener("click", () => selectNode(n.id));
    list.append(b);
  });
  if (!nodes.length)
    list.append(
      el(
        "p",
        state.data.nodes.length
          ? "No claims match these filters."
          : "Source imported, but no theorem-like claims were extracted. See Analysis desk for extraction status.",
        "library-footer",
      ),
    );
  if (nodes.length > 500)
    list.append(
      el(
        "p",
        "Showing the first 500 matching claims. Narrow your search to inspect others.",
        "library-footer",
      ),
    );
}
function selectNode(id) {
  state.selected = id;
  renderClaims();
  renderInspector();
  dirty = true;
}
function renderInspector() {
  const out = $("inspector-content");
  out.replaceChildren();
  const node = state.data?.nodes.find((n) => n.id === state.selected);
  if (!node) {
    out.append(
      el("div", "◎", "empty-orbit"),
      el("h3", "Select a point. Follow the evidence."),
      el(
        "p",
        "Every point represents a claim. Select one to inspect its statement, authored status, and connections.",
        "muted",
      ),
    );
    return;
  }
  out.append(
    el("div", `${human(node.layer)} / ${human(node.kind)}`, "claim-kind"),
    el("h3", node.label),
    el("p", node.statement || "No statement supplied.", "claim-statement"),
  );
  const details = [
    [
      node.status === "EXTRACTION_CANDIDATE"
        ? "Extraction status"
        : "Authored status",
      human(node.status),
    ],
    ["Domain", node.domain || "Unspecified"],
  ];
  if (Number.isFinite(node.uncertainty))
    details.push([
      "Authored uncertainty",
      `${Math.round(node.uncertainty * 100)}%`,
    ]);
  if (node.uncertainty_description)
    details.push(["Extraction uncertainty", node.uncertainty_description]);
  details.push(["Evidence", "Not certified by this view"]);
  details.forEach(([label, value]) => {
    const row = el("div", undefined, "detail-row");
    row.append(el("span", label), el("span", value));
    out.append(row);
  });
  if (node.source) {
    out.append(el("p", "Source provenance", "claim-kind"));
    if (node.source.spans) {
      node.source.spans.forEach((span) => out.append(sourceSpan(span)));
    } else {
      out.append(
        el(
          "p",
          typeof node.source === "string"
            ? node.source
            : JSON.stringify(node.source),
          "claim-statement",
        ),
      );
    }
  }
  if (node.sources?.length) {
    out.append(el("p", "Reference sources", "claim-kind"));
    node.sources.forEach((source) => {
      const link = el("a", source.title || source.url, "connection");
      try {
        const url = new URL(source.url);
        if (url.protocol === "https:") {
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
      } catch (_) {}
      out.append(link);
    });
  }
  if (node.proof?.text) {
    const proof = el("details", undefined, "source-proof");
    proof.append(
      el("summary", "Inspect associated proof text (not verified)"),
      el("p", node.proof.text, "claim-statement"),
    );
    (node.proof.spans || []).forEach((span) => proof.append(sourceSpan(span)));
    out.append(proof);
  }
  const links = state.data.edges.filter(
    (e) => e.source === node.id || e.target === node.id,
  );
  out.append(el("p", `${links.length} connected relationships`, "claim-kind"));
  links.slice(0, 30).forEach((e) => {
    const other = e.source === node.id ? e.target : e.source;
    const target = state.data.nodes.find((n) => n.id === other);
    const b = el(
      "button",
      `${e.source === node.id ? "→" : "←"} ${target?.label || other} · ${human(e.kind)}`,
      "connection",
    );
    b.addEventListener("click", () => selectNode(other));
    out.append(b);
    if (e.rationale) out.append(el("p", e.rationale, "muted"));
    if (e.source_anchor) {
      const evidence = el("details", undefined, "relation-evidence");
      evidence.append(
        el("summary", "Inspect reference evidence"),
        sourceSpan(e.context_anchor || e.source_anchor),
      );
      out.append(evidence);
    }
  });
}
function sourceSpan(span) {
  const box = el("div", undefined, "source-span");
  box.append(
    el(
      "p",
      `Page ${span.page ?? "?"} / characters ${span.char_start ?? span.start ?? span.text_start ?? "?"}–${span.char_end ?? span.end ?? span.text_end ?? "?"}`,
      "claim-kind",
    ),
  );
  if (span.text || span.excerpt)
    box.append(el("p", span.text || span.excerpt, "claim-statement"));
  const hash = span.excerpt_sha256 || span.sha256;
  if (hash) box.append(el("small", `Excerpt SHA-256: ${hash}`, "source-hash"));
  return box;
}
function finding(item) {
  const box = el("article", undefined, "finding");
  box.append(
    el("h4", item.title || item.defect_type || item.name || "Analysis signal"),
    el("p", item.detail || item.description || JSON.stringify(item)),
  );
  return box;
}
function renderFindings() {
  const d = state.data,
    rows = [...(d.findings || [])];
  const preview = $("findings-preview"),
    all = $("all-findings");
  preview.replaceChildren();
  all.replaceChildren();
  if (!rows.length) {
    rows.push({
      title: "No diagnostic findings returned",
      detail: "Absence of findings is not proof of correctness.",
    });
  }
  rows.slice(0, 3).forEach((r) => preview.append(finding(r)));
  rows.forEach((r) => all.append(finding(r)));
  const plan = $("planning");
  plan.replaceChildren();
  const actions = d.planning?.actions || [];
  actions.forEach((action) => {
    const target = d.nodes.find((n) => n.id === action.target);
    plan.append(
      finding({
        title: human(action.kind) + (target ? " / " + target.label : ""),
        detail: `${action.condition || "Review required"} Required artifact: ${action.required_artifact || "Not specified"}. No action has been executed.`,
      }),
    );
  });
  if (!actions.length)
    plan.append(
      el("p", "No evidence-action plan supplied for this view.", "muted"),
    );
  const diagnostics = $("diagnostics");
  diagnostics.replaceChildren();
  Object.entries(d.metrics || {})
    .filter(([, v]) => typeof v === "number" && Number.isFinite(v))
    .forEach(([key, value]) => {
      const row = el("div", undefined, "check");
      row.append(
        el("span", human(key)),
        el("span", Number.isInteger(value) ? value : value.toFixed(3)),
      );
      diagnostics.append(row);
    });
  $("analysis-notice").textContent =
    d.notice ||
    "This view is exploratory and does not certify mathematical claims.";
  const checks = $("checks");
  checks.replaceChildren();
  const values = Array.isArray(d.checks)
    ? d.checks
    : Object.entries(d.checks || {}).map(([name, status]) => ({
        name,
        status,
      }));
  values.forEach((c) => {
    const row = el("div", undefined, "check");
    row.append(
      el("span", c.name || c.checker || c.id || "Check"),
      el(
        "span",
        human(c.execution_status || c.status || c.outcome || "Not reported"),
      ),
    );
    checks.append(row);
  });
  if (!values.length)
    checks.append(el("p", "No execution checks supplied.", "muted"));
  const p = $("provenance");
  p.replaceChildren();
  p.append(
    el(
      "div",
      `Mode: ${human(d.mode)}. Graph geometry is a navigation aid, not a confidence measure.`,
      "provenance-row",
    ),
    el(
      "div",
      "Paper import uses the existing bounded parser with model extraction disabled. It does not run a trusted Lean verifier or accept reviewer attestations.",
      "provenance-row",
    ),
  );
  if (d.provenance)
    p.append(
      el("div", JSON.stringify(d.provenance, null, 2), "provenance-row"),
    );
  if (d.revision)
    p.append(el("div", "Source revision: " + d.revision, "provenance-row"));
}
async function request(path, options) {
  const response = await fetch(path, options);
  let data;
  try {
    data = await response.json();
  } catch {
    throw Error("The local service returned an unreadable response.");
  }
  if (!response.ok)
    throw Error(
      data.error || data.message || `Request failed (${response.status}).`,
    );
  return data;
}
async function loadDemo(example = "reference") {
  if (state.busy) return;
  setBusy(true);
  setStatus("Loading the bundled reference map…");
  try {
    selectData(
      await request(example === "gravity" ? "/api/demo/gravity" : "/api/demo"),
      -1,
    );
    clearStatus();
    view("map");
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    setBusy(false);
  }
}
function setBusy(busy) {
  state.busy = busy;
  ["import-button", "drop-zone", "load-demo", "load-gravity"].forEach(
    (id) => ($(id).disabled = busy),
  );
  $("file-input").disabled = busy;
  $("canvas-wrap").setAttribute("aria-busy", String(busy));
}
async function importFiles(files) {
  if (state.busy) {
    setStatus(
      "An analysis is already running. Please wait before importing another file.",
    );
    return;
  }
  const list = Array.from(files);
  if (!list.length) return;
  if (list.length > 10) {
    setStatus("Please import up to 10 files at a time.", true);
    return;
  }
  setBusy(true);
  let successes = 0;
  const errors = [];
  for (let i = 0; i < list.length; i++) {
    const file = list[i];
    setStatus(
      `Analyzing ${i + 1} of ${list.length}: ${file.name}. Bounded local extraction, not proof verification…`,
    );
    try {
      if (!/\.(pdf|tex|json)$/i.test(file.name))
        throw Error("Use a PDF, TeX or Proof Map JSON file.");
      if (file.size > 8 * 1024 * 1024)
        throw Error("File exceeds the 8 MiB limit.");
      if (/\.(pdf|tex)$/i.test(file.name) && file.size > 4000000)
        throw Error("Paper exceeds the 4 MB limit (4,000,000 bytes).");
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let p = 0; p < bytes.length; p += 32768)
        binary += String.fromCharCode(...bytes.subarray(p, p + 32768));
      const data = await request("/api/analyze", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Proofmap-Studio": "1",
        },
        body: JSON.stringify({ name: file.name, content: btoa(binary) }),
      });
      state.sessions.push({
        title: file.name,
        data,
        at: new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
      });
      selectData(data, state.sessions.length - 1);
      successes++;
    } catch (e) {
      errors.push(`${file.name}: ${e.message}`);
    }
  }
  setBusy(false);
  $("file-input").value = "";
  if (successes) view("map");
  if (errors.length)
    setStatus(`${successes} analyzed. ${errors.join(" ")}`, true);
  else
    setStatus(
      `${successes} ${successes === 1 ? "file" : "files"} analyzed locally. Source assertions remain unverified.`,
    );
}
$("import-button").onclick = () => {
  if (!state.busy) $("file-input").click();
};
$("drop-zone").onclick = () => {
  if (!state.busy) $("file-input").click();
};
$("file-input").onchange = (e) => importFiles(e.target.files);
$("load-demo").onclick = () => loadDemo();
$("load-gravity").onclick = () => loadDemo("gravity");
window.addEventListener("dragenter", (e) => {
  if (e.dataTransfer?.types.includes("Files")) {
    e.preventDefault();
    dragDepth++;
    $("drop-overlay").classList.remove("hidden");
  }
});
window.addEventListener("dragover", (e) => {
  if (e.dataTransfer?.types.includes("Files")) e.preventDefault();
});
window.addEventListener("dragleave", (e) => {
  if (e.dataTransfer?.types.includes("Files") && --dragDepth <= 0) {
    dragDepth = 0;
    $("drop-overlay").classList.add("hidden");
  }
});
window.addEventListener("drop", (e) => {
  if (e.dataTransfer?.files.length) {
    e.preventDefault();
    dragDepth = 0;
    $("drop-overlay").classList.add("hidden");
    importFiles(e.dataTransfer.files);
  }
});
function download(blob, name) {
  const url = URL.createObjectURL(blob),
    a = el("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function exportJSON() {
  if (state.data)
    download(
      new Blob([JSON.stringify(state.data, null, 2)], {
        type: "application/json",
      }),
      "proof-map-analysis.json",
    );
}
$("export-json").onclick = exportJSON;
$("analysis-export").onclick = exportJSON;
$("search").oninput = (e) => {
  state.query = e.target.value.trim().toLowerCase();
  renderClaims();
  dirty = true;
};
document.querySelectorAll("[data-layer]").forEach(
  (n) =>
    (n.onchange = () => {
      n.checked
        ? state.layers.add(n.dataset.layer)
        : state.layers.delete(n.dataset.layer);
      renderClaims();
      dirty = true;
    }),
);
function projection(mode) {
  state.projection = mode;
  ["sphere", "atlas"].forEach((n) => {
    $(n + "-mode").classList.toggle("selected", n === mode);
    $(n + "-mode").setAttribute("aria-pressed", String(n === mode));
  });
  dirty = true;
}
$("sphere-mode").onclick = () => projection("sphere");
$("atlas-mode").onclick = () => projection("atlas");
function zoom(delta) {
  state.zoom = Math.min(2.8, Math.max(0.45, state.zoom * delta));
  dirty = true;
}
$("zoom-in").onclick = () => zoom(1.15);
$("zoom-out").onclick = () => zoom(1 / 1.15);
$("reset-view").onclick = () => {
  state.yaw = 0.45;
  state.pitch = 0.18;
  state.zoom = 1;
  dirty = true;
};
$("rotate").onclick = () => {
  state.rotate = !state.rotate;
  $("rotate").textContent = state.rotate ? "Ⅱ" : "▷";
  $("rotate").setAttribute("aria-pressed", String(state.rotate));
  $("rotate").setAttribute(
    "aria-label",
    state.rotate ? "Pause automatic rotation" : "Start automatic rotation",
  );
  dirty = true;
};
$("save-image").onclick = () => {
  draw();
  canvas.toBlob((blob) => {
    if (blob) download(blob, "proof-map-boundary.png");
  });
};
function resize() {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  width = rect.width;
  height = rect.height;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  dirty = true;
}
new ResizeObserver(resize).observe($("canvas-wrap"));
function position(n, i, total) {
  const sp = state.data.surface?.points?.[n.id];
  if (sp && Number.isFinite(sp.longitude) && Number.isFinite(sp.latitude)) {
    return { lon: sp.longitude, lat: sp.latitude, r: sp.radius || 1 };
  }
  const lon = i * 2.399963229728653,
    lat = Math.asin(1 - (2 * (i + 0.5)) / Math.max(total, 1));
  return {
    lon,
    lat,
    r: { CORE: 0.31, INTERIOR: 0.65, BOUNDARY: 1, EXTERIOR: 1.15 }[n.layer],
  };
}
function project(lon, lat, r = 1) {
  const radius = Math.min(width * 0.35, height * 0.39) * state.zoom;
  if (state.projection === "atlas")
    return {
      x:
        width / 2 +
        ((((((lon + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) -
          Math.PI) /
          Math.PI) *
          radius *
          1.3,
      y: height / 2 - (lat / (Math.PI / 2)) * radius * 0.85,
      z: 0,
    };
  let x = Math.cos(lat) * Math.sin(lon + state.yaw) * r,
    z = Math.cos(lat) * Math.cos(lon + state.yaw) * r,
    y = Math.sin(lat) * r;
  const yp = y * Math.cos(state.pitch) - z * Math.sin(state.pitch),
    zp = y * Math.sin(state.pitch) + z * Math.cos(state.pitch);
  return { x: width / 2 + x * radius, y: height / 2 - yp * radius, z: zp };
}
function curve(points, color, lineWidth = 1) {
  ctx.beginPath();
  points.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.stroke();
}
function draw() {
  if (!width || !height) return;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0c1620";
  ctx.fillRect(0, 0, width, height);
  const gradient = ctx.createRadialGradient(
    width / 2,
    height / 2,
    10,
    width / 2,
    height / 2,
    width * 0.5,
  );
  gradient.addColorStop(0, "#16313b");
  gradient.addColorStop(1, "#0c1620");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "#56708530";
  for (let x = 16; x < width; x += 26)
    for (let y = 20; y < height; y += 26) {
      ctx.beginPath();
      ctx.arc(x, y, 0.65, 0, Math.PI * 2);
      ctx.fill();
    }
  for (let lat = -Math.PI / 2 + 0.26; lat < Math.PI / 2; lat += Math.PI / 8) {
    const pts = [];
    for (let l = -Math.PI; l <= Math.PI + 0.01; l += 0.035)
      pts.push(project(l, lat));
    curve(pts, "#628d9a25");
  }
  for (let l = -Math.PI; l < Math.PI; l += Math.PI / 8) {
    const pts = [];
    for (let lat = -Math.PI / 2; lat < Math.PI / 2 + 0.01; lat += 0.035)
      pts.push(project(l, lat));
    curve(pts, "#628d9a25");
  }
  if (!state.data) return;
  const nodes = visibleNodes();
  const index = new Map(state.data.nodes.map((n, i) => [n.id, i]));
  state.points = nodes.slice(0, 500).map((n) => {
    const p = position(n, index.get(n.id), state.data.nodes.length);
    return { ...project(p.lon, p.lat, p.r), node: n };
  });
  const byId = new Map(state.points.map((p) => [p.node.id, p]));
  const selected = state.selected;
  for (const e of state.data.edges) {
    const a = byId.get(e.source),
      b = byId.get(e.target);
    if (!a || !b) continue;
    const connected =
      selected && (e.source === selected || e.target === selected);
    curve(
      [a, b],
      connected ? "#91dedaaa" : selected ? "#53758a1a" : "#729ba940",
      connected ? 1.4 : 0.7,
    );
  }
  const connectedIds = new Set();
  if (selected)
    state.data.edges.forEach((e) => {
      if (e.source === selected) connectedIds.add(e.target);
      if (e.target === selected) connectedIds.add(e.source);
    });
  state.points.sort((a, b) => a.z - b.z);
  const labelBoxes = [];
  for (const p of state.points) {
    const color = colors[p.node.layer],
      active = p.node.id === selected,
      related = connectedIds.has(p.node.id),
      opacity = selected && !active && !related ? 0.25 : p.z < -0.1 ? 0.55 : 1;
    ctx.globalAlpha = opacity;
    ctx.beginPath();
    ctx.arc(p.x, p.y, active ? 15 : 8, 0, Math.PI * 2);
    ctx.fillStyle = color + "12";
    ctx.fill();
    if (active) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 11, 0, Math.PI * 2);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(p.x, p.y, active ? 4.5 : related ? 3.7 : 2.8, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    if (
      active ||
      related ||
      (!selected &&
        p.z > 0.15 &&
        index.get(p.node.id) % Math.max(1, Math.ceil(nodes.length / 12)) === 0)
    ) {
      ctx.font = "9px Segoe UI,Arial,sans-serif";
      ctx.fillStyle = "#c4d7df";
      const label =
        p.node.label.length > 25
          ? p.node.label.slice(0, 23) + "…"
          : p.node.label;
      const tx = p.x + 10,
        ty = p.y - 7;
      if (
        tx + ctx.measureText(label).width < width - 40 &&
        ty > 35 &&
        ty < height - 30
      ) {
        const box = {
          x: tx,
          y: ty - 10,
          w: ctx.measureText(label).width,
          h: 13,
        };
        if (
          !labelBoxes.some(
            (b) =>
              box.x < b.x + b.w + 4 &&
              box.x + box.w + 4 > b.x &&
              box.y < b.y + b.h &&
              box.y + box.h > b.y,
          )
        ) {
          ctx.fillText(label, tx, ty);
          labelBoxes.push(box);
        }
      }
    }
    ctx.globalAlpha = 1;
  }
  ctx.fillStyle = "#7792a2";
  ctx.font = "8px Segoe UI,Arial,sans-serif";
  ctx.fillText(
    state.data.mode === "paper"
      ? "SOURCE DEPENDENCY VIEW / ASSERTIONS UNVERIFIED"
      : "AUTHORED REFERENCE MAP / GEOMETRY IS HEURISTIC",
    20,
    height - 35,
  );
  if (nodes.length > 500)
    ctx.fillText("First 500 matching claims shown", 20, 47);
}
canvas.addEventListener("pointerdown", (e) => {
  drag = {
    x: e.clientX,
    y: e.clientY,
    startX: e.clientX,
    startY: e.clientY,
    moved: false,
  };
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x,
    dy = e.clientY - drag.y;
  if (Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > 4)
    drag.moved = true;
  if (state.projection === "sphere") {
    state.yaw += dx * 0.006;
    state.pitch = Math.max(-1.4, Math.min(1.4, state.pitch + dy * 0.006));
  }
  drag.x = e.clientX;
  drag.y = e.clientY;
  dirty = true;
});
canvas.addEventListener("pointerup", (e) => {
  if (drag && !drag.moved) {
    const rect = canvas.getBoundingClientRect(),
      x = e.clientX - rect.left,
      y = e.clientY - rect.top;
    const hit = [...state.points]
      .reverse()
      .find((p) => Math.hypot(p.x - x, p.y - y) < 12);
    if (hit) selectNode(hit.node.id);
  }
  drag = null;
});
canvas.addEventListener("pointercancel", () => (drag = null));
canvas.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    zoom(e.deltaY > 0 ? 0.94 : 1.06);
  },
  { passive: false },
);
function frame(now) {
  if (state.rotate && state.projection === "sphere" && !document.hidden) {
    state.yaw += Math.min(now - lastFrame, 50) * 0.00015;
    dirty = true;
  }
  lastFrame = now;
  if (dirty) {
    draw();
    dirty = false;
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
if (reducedMotion)
  $("rotate").title =
    "Start optional rotation (reduced motion respected by default)";
loadDemo();
