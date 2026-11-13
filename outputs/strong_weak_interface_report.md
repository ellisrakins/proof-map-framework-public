# Strong–Weak Interface Proof Map — Proof Boundary Analysis

A typed boundary map for the interface where weak quark currents act inside QCD-bound hadrons and nuclei. The purpose is not to solve QCD, but to expose where formal derivation, empirical calibration, approximation, and proof gaps meet.

## Geometry metrics

| Metric | Value | Interpretation |
|---|---:|---|
| `explanatory_volume` | 30.28 | Weighted amount of nontrivial content currently enclosed by the proof map. |
| `surface_area` | 90.2 | Boundary complexity: open interfaces, assumptions, empirical patches, and uncertainty. |
| `roundness` | 0.1468 | Uniform derivability from the core; higher means less jagged proof distance across the boundary. |
| `density` | 0.218 | Explanatory volume per unit proof/derivation cost. |
| `closure_ratio` | 0.182 | Weighted share of boundary nodes with a classified closure path. |
| `uncertainty_thickness` | 0.6029 | Average thickness of probabilistic, empirical, approximate, or unresolved boundary regions. |
| `hole_count` | 5 | Boundary/exterior nodes not derivably connected to the core or still gaplike. |
| `seam_count` | 12 | Cross-domain or approximation interfaces with tension/uncertainty. |
| `gap_count` | 5 | Nodes explicitly marked as gap, blocked, or external. |
| `unexplained_parameter_count` | 1 | Empirical/assumed constants that remain boundary defects. |

## Diagnosis

- 5 boundary/exterior nodes are not reachable from the core.
- 12 interface or cross-domain seam edges detected.
- 5 gaplike nodes require closure work.

## Highest-severity proof-boundary defects

| Rank | Defect | Type | Severity | Closure path | Affected downstream nodes |
|---:|---|---|---:|---|---|
| 1 | `qcd.confinement` | proof_gap | 21 | modeling + proof | boundary.ckm_first_row_unitarity, boundary.radiative_box_corrections, interface.weak_current_inside_hadron, nuclear.chiral_eft_matching, nuclear.many_body_matrix_element, phenomenon.neutron_beta_decay, +2 more |
| 2 | `nuclear.many_body_matrix_element` | proof_gap | 12.5 | modeling + proof | boundary.ckm_first_row_unitarity, phenomenon.nuclear_beta_decay |
| 3 | `qcd.yang_mills_mass_gap` | proof_gap | 11 | modeling + proof | — |
| 4 | `external.bsm_interface_exclusion` | blocked_or_external | 8.75 | modeling + proof | boundary.ckm_first_row_unitarity |
| 5 | `boundary.ckm_first_row_unitarity` | proof_gap | 8.5 | experiment + bridge theorem | — |
| 6 | `ew.ckm_matrix` | unexplained_parameter | 3.05 | derive, constrain experimentally, or mark as irreducible boundary condition | ew.ckm_matrix, boundary.ckm_first_row_unitarity, interface.weak_current_inside_hadron, phenomenon.neutron_beta_decay |
| 7 | `external.bsm_interface_exclusion->boundary.ckm_first_row_unitarity` | seam_or_interface_tension | 2.55 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | external.bsm_interface_exclusion, boundary.ckm_first_row_unitarity |
| 8 | `nuclear.many_body_matrix_element->phenomenon.nuclear_beta_decay` | seam_or_interface_tension | 1.596 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | nuclear.many_body_matrix_element, phenomenon.nuclear_beta_decay |
| 9 | `nuclear.chiral_eft_matching->nuclear.many_body_matrix_element` | seam_or_interface_tension | 1.554 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | nuclear.chiral_eft_matching, nuclear.many_body_matrix_element |
| 10 | `ew.charged_weak_current->interface.weak_current_inside_hadron` | seam_or_interface_tension | 1.522 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | ew.charged_weak_current, interface.weak_current_inside_hadron |
| 11 | `qcd.hadron_bound_states->interface.weak_current_inside_hadron` | seam_or_interface_tension | 1.522 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | qcd.hadron_bound_states, interface.weak_current_inside_hadron |
| 12 | `qcd.hadron_bound_states->boundary.radiative_box_corrections` | seam_or_interface_tension | 1.491 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | qcd.hadron_bound_states, boundary.radiative_box_corrections |

## Closure-priority simulation

This estimates which single-node closure would most improve the current proof geometry. It is a heuristic planning aid, not a proof result.

| Rank | Candidate | Current → proposed | Δ volume | Δ surface | Δ roundness | Δ closure | Δ thickness | Score | Rationale |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `qcd.yang_mills_mass_gap` | GAP → PROVED | 6.44 | -8.98 | 0.0886 | 0.1099 | -0.0979 | 1.992 | mathematical proof closure |
| 2 | `qcd.confinement` | GAP → PROVED | 6.44 | -8.63 | 0.0886 | 0.1099 | -0.0919 | 1.969 | mathematical proof closure |
| 3 | `nuclear.many_body_matrix_element` | GAP → PROVED | 5.52 | -7.23 | 0.0886 | 0.1099 | -0.0681 | 1.759 | mathematical proof closure |
| 4 | `boundary.ckm_first_row_unitarity` | GAP → PROVED | 4.6 | -5.407 | 0.0775 | 0.0961 | -0.0439 | 1.45 | mathematical proof closure |
| 5 | `interface.weak_current_inside_hadron` | APPROXIMATION → DERIVED | 3.189 | -3.11 | 0.0512 | 0.0635 | -0.0322 | 0.9702 | replace approximation with limit/matching theorem and controlled error |
| 6 | `boundary.radiative_box_corrections` | APPROXIMATION → DERIVED | 2 | -2.049 | 0.0361 | 0.0448 | -0.0179 | 0.6377 | replace approximation with limit/matching theorem and controlled error |
| 7 | `ew.ckm_matrix` | EMPIRICAL → DERIVED | 1.316 | -0.555 | 0.0198 | 0.0246 | -0.0075 | 0.3568 | derive parameter or classify it as irreducible with bounded uncertainty |
| 8 | `external.bsm_interface_exclusion` | EXTERNAL → EMPIRICAL | 0 | -7.656 | 0.0118 | 0.0147 | -0.0169 | 0.3548 | move external region onto the boundary via exclusion or incorporation |

## Boundary ledger

| Node | Layer | Status | Domain | Proof distance | Uncertainty | Statement |
|---|---|---|---|---:|---:|---|
| `boundary.ckm_first_row_unitarity` | BOUNDARY | GAP | phenomenology | 2 | 0.5 | Precision extractions of Vud, Vus, Vub test whether the first row closes as expected. |
| `boundary.radiative_box_corrections` | BOUNDARY | APPROXIMATION | strong_weak_interface | 1 | 0.38 | Electroweak/QCD loop and box corrections connect measured beta decay to CKM parameters. |
| `ew.ckm_matrix` | BOUNDARY | EMPIRICAL | electroweak | 3 | 0.22 | Empirical flavor-mixing parameters control charged-current quark transitions. |
| `external.bsm_interface_exclusion` | EXTERIOR | EXTERNAL | beyond_standard_model | ∞ | 0.75 | Alternative interactions must be bounded or incorporated if precision interface tensions persist. |
| `interface.weak_current_inside_hadron` | BOUNDARY | APPROXIMATION | strong_weak_interface | 3 | 0.45 | Compute ⟨H_f \| J_weak \| H_i⟩ where H_i,H_f are QCD-bound hadronic states. |
| `nuclear.many_body_matrix_element` | BOUNDARY | GAP | nuclear | 5 | 0.65 | Derive weak transition amplitudes in nuclei from matched QCD/EFT/many-body dynamics with controlled error b… |
| `phenomenon.neutron_beta_decay` | BOUNDARY | EMPIRICAL | phenomenology | 4 | 0.18 | n → p + e⁻ + anti-νe; observed decay rate depends on weak coupling and hadronic/nuclear matrix elements. |
| `phenomenon.nuclear_beta_decay` | BOUNDARY | EMPIRICAL | phenomenology | 6 | 0.28 | Weak nuclear transitions probe the strong–weak interface and nuclear many-body modeling. |
| `qcd.confinement` | BOUNDARY | GAP | qcd | 2 | 0.85 | Free colored asymptotic states do not appear; hadrons are color singlets. |
| `qcd.yang_mills_mass_gap` | BOUNDARY | GAP | qcd | 2 | 0.9 | A rigorous four-dimensional Yang–Mills mass gap is required for a mathematically sealed strong-force founda… |

## Proof map nodes

| Node | Kind | Status | Layer | Domain | Weight | Cost | Notes |
|---|---|---|---|---|---:|---:|---|
| `ew.ckm_matrix` | CONSTANT | EMPIRICAL | BOUNDARY | electroweak | 4 | 1 | Algebraically part of the Standard Model, but the numerical values remain empirical inputs h… |
| `nuclear.many_body_matrix_element` | INTERFACE | GAP | BOUNDARY | nuclear | 6 | 7 | Active proof boundary for beta decay, double beta decay, and neutrino–nucleus scattering. |
| `boundary.ckm_first_row_unitarity` | OBSERVATION | GAP | BOUNDARY | phenomenology | 5 | 3 | Boundary tension: could be radiative corrections, nuclear structure, lattice inputs, or beyo… |
| `phenomenon.neutron_beta_decay` | PHENOMENON | EMPIRICAL | BOUNDARY | phenomenology | 5 | 2 | n → p + e⁻ + anti-νe; observed decay rate depends on weak coupling and hadronic/nuclear matr… |
| `phenomenon.nuclear_beta_decay` | PHENOMENON | EMPIRICAL | BOUNDARY | phenomenology | 5 | 2 | Weak nuclear transitions probe the strong–weak interface and nuclear many-body modeling. |
| `qcd.confinement` | GAP | GAP | BOUNDARY | qcd | 7 | 8 | Physically central and numerically supported, but not closed as a rigorous derivation in thi… |
| `qcd.yang_mills_mass_gap` | GAP | GAP | BOUNDARY | qcd | 7 | 8 | Deep foundational proof hole on the strong-force side. |
| `boundary.radiative_box_corrections` | BRIDGE | APPROXIMATION | BOUNDARY | strong_weak_interface | 4 | 5 | Electroweak/QCD loop and box corrections connect measured beta decay to CKM parameters. |
| `interface.weak_current_inside_hadron` | INTERFACE | APPROXIMATION | BOUNDARY | strong_weak_interface | 6 | 6 | This is the central strong–weak seam: clean weak operator, nonperturbative hadron state. |
| `core.quantum_field_theory` | AXIOM | CORE | CORE | foundation | 5 | 3 | The rigorous mathematical foundation of interacting four-dimensional QFT remains a deep math… |
| `core.standard_model_lagrangian` | PRIMITIVE_LAW | CORE | CORE | standard_model | 6 | 2 | Treated here as the working core, not as a mathematically final theory of everything. |
| `external.bsm_interface_exclusion` | GAP | EXTERNAL | EXTERIOR | beyond_standard_model | 5 | 6 | Alternative interactions must be bounded or incorporated if precision interface tensions per… |
| `ew.charged_weak_current` | THEOREM | DERIVED | INTERIOR | electroweak | 4 | 2 | The W-mediated charged current changes quark flavor. |
| `ew.su2_u1_electroweak_sector` | DEFINITION | DERIVED | INTERIOR | electroweak | 5 | 2 | Weak isospin, hypercharge, gauge bosons, and Higgs mechanism define electroweak interactions. |
| `nuclear.chiral_eft_matching` | BRIDGE | APPROXIMATION | INTERIOR | nuclear | 4 | 4 | Low-energy nuclear interactions and currents are represented by symmetry-constrained effecti… |
| `qcd.asymptotic_freedom` | THEOREM | PROVED | INTERIOR | qcd | 4 | 3 | The QCD coupling weakens at short distance/high momentum transfer. |
| `qcd.hadron_bound_states` | MODEL | COMPUTED | INTERIOR | qcd | 5 | 5 | Protons, neutrons, mesons, and form factors emerge from nonperturbative QCD calculations and… |
| `qcd.lattice_form_factors` | BRIDGE | COMPUTED | INTERIOR | qcd | 4 | 5 | Computational closure path with finite-volume, discretization, chiral, and continuum uncerta… |
| `qcd.su3_color_gauge_sector` | DEFINITION | DERIVED | INTERIOR | qcd | 5 | 2 | Quarks carry color; gluons mediate color interactions. |

## How to read this map

- **Volume** is explanatory content enclosed by the current formal structure.
- **Surface area** is boundary complexity: external assumptions, empirical attachments, patches, and open interfaces.
- **Roundness** is high when boundary phenomena have similar derivational distance from the compact core.
- **Thickness** is classified uncertainty: probabilistic law, approximation, measurement error, computational limits, or unresolved proof debt.
- **Seams** are force/domain/theory interfaces where local charts must be glued by bridge principles.
