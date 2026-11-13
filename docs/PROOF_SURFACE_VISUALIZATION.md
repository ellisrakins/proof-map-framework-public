# Proof Surface Visualization

This extension visualizes a proof map as a **surface**, not only as a radial proof-volume graph.

The surface view is designed for the framework's dynamic interpretation:

```text
surface        = boundary phenomena, observations, interfaces, effective regimes, defects
surface flow   = time / entropy / energy / physical sequence along the boundary
proof fiber    = dependency path from core or interior explanation to surface point
thickness      = uncertainty, approximation, empirical attachment, computation, or proof debt
seam           = interface where two local theory charts must be glued
hole/cavity    = disconnected, blocked, external, or unclosed region
```

## Coordinate model

The software builds deterministic spherical coordinates for every node:

| Coordinate | Meaning |
|---|---|
| Longitude | Domain or local theory chart, such as `qcd`, `electroweak`, `cosmology`, `thermodynamics` |
| Latitude | Cosmic time / active epoch when epoch metadata exists; otherwise proof-distance from the core |
| Radius | Layer depth: `CORE < INTERIOR < BOUNDARY < EXTERIOR` |
| Halo radius | Surface thickness: uncertainty plus status penalty |

This creates two useful modes:

```text
Dynamic map:
    latitude = log-scaled cosmic time / active epoch

Static map:
    latitude = derivational distance from core
```

## Generated artifacts

For each proof map, the surface renderer creates four files:

```text
<basename>_surface_atlas.svg       static unwrapped sphere / surface atlas
<basename>_surface_explorer.html   standalone interactive globe viewer
<basename>_surface_points.csv      point ledger with spherical coordinates and thickness
<basename>_surface_layout.json     complete serialized layout for other tools
```

The interactive HTML requires no external JavaScript libraries. It includes:

```text
rotatable spherical projection
uncertainty halo toggle
boundary-only toggle
flow/seam/gap overlays
epoch slider for dynamic maps
hover inspection panel
boundary point ledger
```

## CLI usage

```bash
python3 -m proofmap.cli surface examples/strong_weak_interface.json --out outputs
python3 -m proofmap.cli surface examples/dynamic_cosmology.json --out outputs
```

The general report and demo commands also emit surface assets:

```bash
python3 -m proofmap.cli report examples/dynamic_cosmology.json --out outputs
python3 -m proofmap.cli demo --out .
```

## Interpretation

A surface atlas should be read as follows:

- **Thick red halos**: high-priority unclosed gaps or exterior defects.
- **Orange dashed seams**: approximation/interface/bridge tension between local charts.
- **Blue arrows**: physical flow along the surface, such as cosmic epoch progression.
- **Gray fibers**: proof dependencies from the core or interior into boundary phenomena.
- **Dense clustered seams**: a local chart boundary where formal closure is expensive.

For example, in the strong–weak interface map, the QCD sector creates thick red surface features around confinement and the Yang–Mills mass gap, while orange seams connect weak-current formalism to QCD-bound hadronic and nuclear matrix elements.

In the dynamic cosmology map, the early-universe boundary, QCD hadronization, entropy/time orientation, and observer/proof-system region become a time-ordered surface rather than a fixed proof shell.
