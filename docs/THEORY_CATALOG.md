# Extensible Theory Catalog

The framework supports standard and emerging theories through an open profile registry, not a closed list embedded in Python enums.

The bundled physics catalog is representative. It does not claim that the set of theories is complete or that every listed research program is empirically credible. A new theory can be added as JSON without changing the graph engine.

## Representation

Each `TheoryProfile` separates five questions:

```text
identity       name, aliases, family, domains, tags
classification theory/framework/model/effective theory/research program/interpretation
epistemics     maturity and evidence status
content        foundations, mathematical frameworks, results, open questions, tests
scope          one or more multidimensional validity regimes
provenance     source IDs and last-verified date
```

Maturity and evidence are deliberately independent. An effective theory may be precision tested in its regime, while an active research program can remain unconfirmed.

### Maturity

```text
ESTABLISHED
EFFECTIVE
ACTIVE_RESEARCH
SPECULATIVE
HISTORICAL
```

### Evidence status

```text
PRECISION_TESTED
EMPIRICALLY_SUPPORTED
INDIRECTLY_SUPPORTED
CONSTRAINED
UNCONFIRMED
DISFAVORED
NOT_APPLICABLE
```

`NOT_APPLICABLE` is useful for mathematical formalisms that are not standalone empirical models.

## Theory Relations

The catalog represents directed or symmetric relationships:

```text
EXTENDS
REDUCES_TO
EFFECTIVE_LIMIT_OF
DUAL_TO
COMPATIBLE_WITH
ALTERNATIVE_TO
CONFLICTS_WITH
USES
UNIFIES
```

Semantic validation rejects missing endpoints, duplicate relations, contradictory compatible/conflicting declarations, and cycles in extension or reduction hierarchies.

## Proof-Map Bindings

Nodes and edges now support:

```text
theory_ids          many-to-many membership in theory charts
formal_systems      mathematical languages used by the claim or dependency
regime_dimensions   open multidimensional scope metadata
```

`regime_dimensions` is intentionally open. A map can record energy, length, temperature, curvature, coupling, particle number, accuracy, computational cutoff, or a domain-specific coordinate without changing the schema.

The current-physics backbone binds shared gaps to every relevant candidate chart. For example, `gap.quantum_gravity` is attached to string/M-theory, loop quantum gravity, asymptotic safety, causal sets, causal dynamical triangulations, group field theory, holography, noncommutative geometry, emergent-spacetime programs, and twistor theory.

## Bundled Coverage

The initial catalog contains:

```text
38 profiles
13 families
52 domain tags
37 theory relations
```

It includes classical physics, relativity, quantum mechanics and quantum field theory, the Standard Model and its sectors, thermodynamics and many-body effective theories, Lambda-CDM and inflation, BSM programs, dark-sector models, modified gravity, and major quantum-gravity approaches.

This is a support matrix, not an endorsement ranking.

## Commands

Validate the catalog, provenance, and current-map bindings:

```bash
proofmap theory-validate \
  examples/theories/physics_theory_catalog.json \
  --sources examples/sources/physics_theory_sources.json \
  --map examples/current_physics_backbone.json \
  --require-sources \
  --require-bindings \
  --report outputs/physics_theory_catalog_report.md
```

List a family:

```bash
proofmap theory-list \
  examples/theories/physics_theory_catalog.json \
  --family quantum_gravity
```

Generate a runnable proof-map scaffold. Declared foundations become core nodes, cataloged results become interior obligations, and open questions and tests remain boundary gaps:

```bash
proofmap theory-scaffold \
  examples/theories/physics_theory_catalog.json \
  loop_quantum_gravity \
  --out outputs/theory_scaffolds/loop_quantum_gravity.json
```

Extract one or more theory charts from a bound map:

```bash
proofmap theory-slice \
  examples/current_physics_backbone.json \
  standard_model \
  --out outputs/theory_slices/standard_model.json \
  --exclude-shared
```

## Adding a Theory

Add a profile to a catalog:

```json
{
  "id": "candidate.example",
  "name": "Example theory",
  "kind": "RESEARCH_PROGRAM",
  "maturity": "ACTIVE_RESEARCH",
  "evidence_status": "UNCONFIRMED",
  "family": "example",
  "summary": "A concise, neutral statement.",
  "domains": ["example_domain"],
  "foundations": ["Declared foundational commitment"],
  "mathematical_frameworks": ["formal_language"],
  "validity_regimes": [
    {
      "id": "primary",
      "description": "Where the proposal claims to apply.",
      "dimensions": {
        "energy_min_gev": 1.0,
        "temperature_max_k": 100.0
      },
      "assumptions": []
    }
  ],
  "key_results": [],
  "open_questions": ["What remains unclosed?"],
  "discriminating_tests": ["What observation could distinguish it?"],
  "source_ids": ["source.example"],
  "last_verified": "2026-07-26",
  "aliases": [],
  "tags": [],
  "metadata": {}
}
```

Then add any `TheoryRelation` records and register the referenced sources. No code changes are required.

## Limits

- The bundled catalog is representative, not exhaustive.
- Profile metadata is structured expert input, not an automated truth assessment.
- Evidence labels do not replace likelihoods, datasets, or replication records.
- A generated scaffold declares obligations; it does not formalize or prove the theory.
- Relations can express compatibility and conflict, but the hypothesis engine does not yet perform joint Bayesian or contradiction-constrained inference.
