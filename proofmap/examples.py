"""Seed proof maps for the boundary-analysis framework."""

from __future__ import annotations

from .model import (
    Edge,
    EdgeKind,
    EdgeStatus,
    Epoch,
    Layer,
    Node,
    NodeKind,
    NodeStatus,
    ProofMap,
)

YEAR_SECONDS = 365.25 * 24 * 3600


def build_minimal_conops_map() -> ProofMap:
    """Build a tiny map that exercises the end-to-end validation workflow."""

    pm = ProofMap(
        title="Minimal CONOPS Validation Map",
        description=(
            "A compact proof-map used to validate the concept of operations: author a typed map, "
            "analyze its boundary, produce artifacts, export Lean obligations, and confirm the "
            "expected open proof debt is detected."
        ),
        metadata={"version": "0.1", "purpose": "conops_validation"},
    )

    def n(**kwargs) -> None:
        pm.add_node(Node(**kwargs))

    n(
        id="core.motion_law",
        label="Ideal motion law",
        kind=NodeKind.PRIMITIVE_LAW,
        status=NodeStatus.CORE,
        layer=Layer.CORE,
        domain="mechanics",
        explanatory_weight=4,
        proof_cost=1,
        uncertainty=0.02,
        statement="A simplified constant-acceleration law governs the test object.",
    )
    n(
        id="model.drop_prediction",
        label="Drop-time prediction",
        kind=NodeKind.THEOREM,
        status=NodeStatus.DERIVED,
        layer=Layer.INTERIOR,
        domain="mechanics",
        explanatory_weight=3,
        proof_cost=2,
        uncertainty=0.05,
        statement="The ideal law predicts a drop time from height and acceleration.",
    )
    n(
        id="boundary.sensor_measurement",
        label="Sensor measurement",
        kind=NodeKind.OBSERVATION,
        status=NodeStatus.EMPIRICAL,
        layer=Layer.BOUNDARY,
        domain="experiment",
        explanatory_weight=3,
        proof_cost=1,
        uncertainty=0.18,
        boundary_weight=2,
        statement="A sensor reports the observed drop time in the validation run.",
    )
    n(
        id="boundary.drag_residual",
        label="Air-drag residual",
        kind=NodeKind.GAP,
        status=NodeStatus.GAP,
        layer=Layer.BOUNDARY,
        domain="experiment",
        explanatory_weight=4,
        proof_cost=3,
        uncertainty=0.65,
        boundary_weight=3,
        statement="The residual between ideal prediction and measurement needs a drag or calibration closure.",
        notes="This intentional gap proves the validator detects unresolved boundary debt.",
    )
    n(
        id="bridge.calibration_model",
        label="Calibration bridge",
        kind=NodeKind.BRIDGE,
        status=NodeStatus.APPROXIMATION,
        layer=Layer.INTERIOR,
        domain="instrumentation",
        explanatory_weight=2,
        proof_cost=2,
        uncertainty=0.25,
        statement="A provisional sensor calibration maps raw timestamps into the measured drop time.",
    )

    def e(
        source: str,
        target: str,
        kind=EdgeKind.PROVES,
        status=EdgeStatus.ACTIVE,
        uncertainty=0.1,
        proof_cost=1.0,
        notes="",
    ) -> None:
        pm.add_edge(
            Edge(
                source=source,
                target=target,
                kind=kind,
                status=status,
                uncertainty=uncertainty,
                proof_cost=proof_cost,
                notes=notes,
            )
        )

    e("core.motion_law", "model.drop_prediction", EdgeKind.PROVES, EdgeStatus.PROVED, 0.03)
    e(
        "model.drop_prediction",
        "boundary.sensor_measurement",
        EdgeKind.EMPIRICALLY_CONSTRAINS,
        EdgeStatus.EMPIRICAL,
        0.18,
    )
    e(
        "model.drop_prediction",
        "boundary.drag_residual",
        EdgeKind.BLOCKS,
        EdgeStatus.GAP,
        0.65,
        notes="Ideal prediction cannot close the empirical residual by itself.",
    )
    e(
        "bridge.calibration_model",
        "boundary.sensor_measurement",
        EdgeKind.BRIDGES,
        EdgeStatus.APPROXIMATE,
        0.25,
    )
    e(
        "boundary.drag_residual",
        "boundary.sensor_measurement",
        EdgeKind.BRIDGES,
        EdgeStatus.GAP,
        0.60,
        notes="Residual closure determines whether the measurement is explained or remains boundary debt.",
    )

    return pm


def build_strong_weak_interface_map() -> ProofMap:
    pm = ProofMap(
        title="Strong–Weak Interface Proof Map",
        description=(
            "A typed boundary map for the interface where weak quark currents act inside "
            "QCD-bound hadrons and nuclei. The purpose is not to solve QCD, but to expose "
            "where formal derivation, empirical calibration, approximation, and proof gaps meet."
        ),
        metadata={"version": "0.2", "framework": "Proof Map Boundary Analysis"},
    )

    def n(**kwargs) -> None:
        pm.add_node(Node(**kwargs))

    # Core structure.
    n(
        id="core.standard_model_lagrangian",
        label="Standard Model Lagrangian",
        kind=NodeKind.PRIMITIVE_LAW,
        status=NodeStatus.CORE,
        layer=Layer.CORE,
        domain="standard_model",
        explanatory_weight=6,
        proof_cost=2,
        uncertainty=0.05,
        statement="Gauge-field, matter-field, Yukawa, Higgs, and interaction structure of the Standard Model.",
        notes="Treated here as the working core, not as a mathematically final theory of everything.",
    )
    n(
        id="core.quantum_field_theory",
        label="Quantum field-theory formalism",
        kind=NodeKind.AXIOM,
        status=NodeStatus.CORE,
        layer=Layer.CORE,
        domain="foundation",
        explanatory_weight=5,
        proof_cost=3,
        uncertainty=0.08,
        statement="Fields, states, amplitudes, renormalization, and operator dynamics supply the formal substrate.",
        notes="The rigorous mathematical foundation of interacting four-dimensional QFT remains a deep mathematical frontier.",
    )

    # Interior domains.
    n(
        id="qcd.su3_color_gauge_sector",
        label="QCD SU(3)c color sector",
        kind=NodeKind.DEFINITION,
        status=NodeStatus.DERIVED,
        layer=Layer.INTERIOR,
        domain="qcd",
        explanatory_weight=5,
        proof_cost=2,
        uncertainty=0.08,
        statement="Quarks carry color; gluons mediate color interactions.",
    )
    n(
        id="ew.su2_u1_electroweak_sector",
        label="Electroweak SU(2)L×U(1)Y sector",
        kind=NodeKind.DEFINITION,
        status=NodeStatus.DERIVED,
        layer=Layer.INTERIOR,
        domain="electroweak",
        explanatory_weight=5,
        proof_cost=2,
        uncertainty=0.07,
        statement="Weak isospin, hypercharge, gauge bosons, and Higgs mechanism define electroweak interactions.",
    )
    n(
        id="ew.charged_weak_current",
        label="Charged weak quark current",
        kind=NodeKind.THEOREM,
        status=NodeStatus.DERIVED,
        layer=Layer.INTERIOR,
        domain="electroweak",
        explanatory_weight=4,
        proof_cost=2,
        uncertainty=0.08,
        statement="The W-mediated charged current changes quark flavor.",
    )
    n(
        id="ew.ckm_matrix",
        label="CKM mixing matrix",
        kind=NodeKind.CONSTANT,
        status=NodeStatus.EMPIRICAL,
        layer=Layer.BOUNDARY,
        domain="electroweak",
        explanatory_weight=4,
        proof_cost=1,
        uncertainty=0.22,
        boundary_weight=2.5,
        statement="Empirical flavor-mixing parameters control charged-current quark transitions.",
        notes="Algebraically part of the Standard Model, but the numerical values remain empirical inputs here.",
    )
    n(
        id="qcd.asymptotic_freedom",
        label="Asymptotic freedom",
        kind=NodeKind.THEOREM,
        status=NodeStatus.PROVED,
        layer=Layer.INTERIOR,
        domain="qcd",
        explanatory_weight=4,
        proof_cost=3,
        uncertainty=0.05,
        statement="The QCD coupling weakens at short distance/high momentum transfer.",
    )
    n(
        id="qcd.yang_mills_mass_gap",
        label="Yang–Mills mass gap",
        kind=NodeKind.GAP,
        status=NodeStatus.GAP,
        layer=Layer.BOUNDARY,
        domain="qcd",
        explanatory_weight=7,
        proof_cost=8,
        uncertainty=0.9,
        boundary_weight=4,
        statement="A rigorous four-dimensional Yang–Mills mass gap is required for a mathematically sealed strong-force foundation.",
        notes="Deep foundational proof hole on the strong-force side.",
    )
    n(
        id="qcd.confinement",
        label="Color confinement",
        kind=NodeKind.GAP,
        status=NodeStatus.GAP,
        layer=Layer.BOUNDARY,
        domain="qcd",
        explanatory_weight=7,
        proof_cost=8,
        uncertainty=0.85,
        boundary_weight=4,
        statement="Free colored asymptotic states do not appear; hadrons are color singlets.",
        notes="Physically central and numerically supported, but not closed as a rigorous derivation in this map.",
    )
    n(
        id="qcd.hadron_bound_states",
        label="Hadron bound states",
        kind=NodeKind.MODEL,
        status=NodeStatus.COMPUTED,
        layer=Layer.INTERIOR,
        domain="qcd",
        explanatory_weight=5,
        proof_cost=5,
        uncertainty=0.35,
        statement="Protons, neutrons, mesons, and form factors emerge from nonperturbative QCD calculations and models.",
    )
    n(
        id="interface.weak_current_inside_hadron",
        label="Weak current inside hadron",
        kind=NodeKind.INTERFACE,
        status=NodeStatus.APPROXIMATION,
        layer=Layer.BOUNDARY,
        domain="strong_weak_interface",
        explanatory_weight=6,
        proof_cost=6,
        uncertainty=0.45,
        boundary_weight=4,
        statement="Compute ⟨H_f | J_weak | H_i⟩ where H_i,H_f are QCD-bound hadronic states.",
        notes="This is the central strong–weak seam: clean weak operator, nonperturbative hadron state.",
    )
    n(
        id="qcd.lattice_form_factors",
        label="Lattice QCD form factors",
        kind=NodeKind.BRIDGE,
        status=NodeStatus.COMPUTED,
        layer=Layer.INTERIOR,
        domain="qcd",
        explanatory_weight=4,
        proof_cost=5,
        uncertainty=0.25,
        statement="Numerical nonperturbative QCD estimates of electroweak decay constants and form factors.",
        notes="Computational closure path with finite-volume, discretization, chiral, and continuum uncertainties.",
    )
    n(
        id="nuclear.chiral_eft_matching",
        label="Chiral EFT matching",
        kind=NodeKind.BRIDGE,
        status=NodeStatus.APPROXIMATION,
        layer=Layer.INTERIOR,
        domain="nuclear",
        explanatory_weight=4,
        proof_cost=4,
        uncertainty=0.35,
        statement="Low-energy nuclear interactions and currents are represented by symmetry-constrained effective field theory.",
    )
    n(
        id="nuclear.many_body_matrix_element",
        label="Nuclear many-body matrix element",
        kind=NodeKind.INTERFACE,
        status=NodeStatus.GAP,
        layer=Layer.BOUNDARY,
        domain="nuclear",
        explanatory_weight=6,
        proof_cost=7,
        uncertainty=0.65,
        boundary_weight=4,
        statement="Derive weak transition amplitudes in nuclei from matched QCD/EFT/many-body dynamics with controlled error bounds.",
        notes="Active proof boundary for beta decay, double beta decay, and neutrino–nucleus scattering.",
    )
    n(
        id="phenomenon.neutron_beta_decay",
        label="Neutron beta decay",
        kind=NodeKind.PHENOMENON,
        status=NodeStatus.EMPIRICAL,
        layer=Layer.BOUNDARY,
        domain="phenomenology",
        explanatory_weight=5,
        proof_cost=2,
        uncertainty=0.18,
        boundary_weight=3,
        statement="n → p + e⁻ + anti-νe; observed decay rate depends on weak coupling and hadronic/nuclear matrix elements.",
    )
    n(
        id="phenomenon.nuclear_beta_decay",
        label="Nuclear beta decay",
        kind=NodeKind.PHENOMENON,
        status=NodeStatus.EMPIRICAL,
        layer=Layer.BOUNDARY,
        domain="phenomenology",
        explanatory_weight=5,
        proof_cost=2,
        uncertainty=0.28,
        boundary_weight=3,
        statement="Weak nuclear transitions probe the strong–weak interface and nuclear many-body modeling.",
    )
    n(
        id="boundary.ckm_first_row_unitarity",
        label="CKM first-row closure",
        kind=NodeKind.OBSERVATION,
        status=NodeStatus.GAP,
        layer=Layer.BOUNDARY,
        domain="phenomenology",
        explanatory_weight=5,
        proof_cost=3,
        uncertainty=0.50,
        boundary_weight=3.5,
        statement="Precision extractions of Vud, Vus, Vub test whether the first row closes as expected.",
        notes="Boundary tension: could be radiative corrections, nuclear structure, lattice inputs, or beyond-Standard-Model physics.",
    )
    n(
        id="boundary.radiative_box_corrections",
        label="Radiative and box corrections",
        kind=NodeKind.BRIDGE,
        status=NodeStatus.APPROXIMATION,
        layer=Layer.BOUNDARY,
        domain="strong_weak_interface",
        explanatory_weight=4,
        proof_cost=5,
        uncertainty=0.38,
        boundary_weight=3,
        statement="Electroweak/QCD loop and box corrections connect measured beta decay to CKM parameters.",
    )
    n(
        id="external.bsm_interface_exclusion",
        label="Beyond-SM exclusion at interface",
        kind=NodeKind.GAP,
        status=NodeStatus.EXTERNAL,
        layer=Layer.EXTERIOR,
        domain="beyond_standard_model",
        explanatory_weight=5,
        proof_cost=6,
        uncertainty=0.75,
        boundary_weight=2.5,
        statement="Alternative interactions must be bounded or incorporated if precision interface tensions persist.",
    )

    def e(
        source: str,
        target: str,
        kind=EdgeKind.PROVES,
        status=EdgeStatus.ACTIVE,
        uncertainty=0.1,
        weight=1.0,
        proof_cost=1.0,
        notes="",
    ) -> None:
        pm.add_edge(
            Edge(
                source=source,
                target=target,
                kind=kind,
                status=status,
                uncertainty=uncertainty,
                weight=weight,
                proof_cost=proof_cost,
                notes=notes,
            )
        )

    e(
        "core.standard_model_lagrangian",
        "qcd.su3_color_gauge_sector",
        EdgeKind.DEFINES,
        EdgeStatus.PROVED,
        0.05,
    )
    e(
        "core.standard_model_lagrangian",
        "ew.su2_u1_electroweak_sector",
        EdgeKind.DEFINES,
        EdgeStatus.PROVED,
        0.05,
    )
    e(
        "core.quantum_field_theory",
        "qcd.asymptotic_freedom",
        EdgeKind.PROVES,
        EdgeStatus.PROVED,
        0.05,
        proof_cost=2,
    )
    e(
        "qcd.su3_color_gauge_sector",
        "qcd.asymptotic_freedom",
        EdgeKind.PROVES,
        EdgeStatus.PROVED,
        0.05,
        proof_cost=2,
    )
    e(
        "qcd.su3_color_gauge_sector",
        "qcd.yang_mills_mass_gap",
        EdgeKind.BLOCKS,
        EdgeStatus.GAP,
        0.9,
        notes="The rigorous foundation of confinement-like behavior requires a mass-gap theorem.",
    )
    e(
        "qcd.su3_color_gauge_sector",
        "qcd.confinement",
        EdgeKind.BLOCKS,
        EdgeStatus.GAP,
        0.85,
        notes="Confinement is a physical pillar and mathematical proof gap.",
    )
    e(
        "qcd.confinement",
        "qcd.hadron_bound_states",
        EdgeKind.PROVES,
        EdgeStatus.APPROXIMATE,
        0.45,
        proof_cost=3,
    )
    e(
        "qcd.lattice_form_factors",
        "qcd.hadron_bound_states",
        EdgeKind.EMPIRICALLY_CONSTRAINS,
        EdgeStatus.COMPUTED,
        0.25,
        proof_cost=3,
    )
    e(
        "ew.su2_u1_electroweak_sector",
        "ew.charged_weak_current",
        EdgeKind.PROVES,
        EdgeStatus.PROVED,
        0.08,
    )
    e("ew.charged_weak_current", "ew.ckm_matrix", EdgeKind.DEFINES, EdgeStatus.EMPIRICAL, 0.22)
    e(
        "ew.charged_weak_current",
        "interface.weak_current_inside_hadron",
        EdgeKind.INTERFACE,
        EdgeStatus.APPROXIMATE,
        0.45,
        proof_cost=3,
        notes="Weak operator is inserted into a strongly-bound state.",
    )
    e(
        "qcd.hadron_bound_states",
        "interface.weak_current_inside_hadron",
        EdgeKind.INTERFACE,
        EdgeStatus.APPROXIMATE,
        0.45,
        proof_cost=4,
        notes="Hadronic states carry nonperturbative QCD uncertainty.",
    )
    e(
        "ew.ckm_matrix",
        "interface.weak_current_inside_hadron",
        EdgeKind.BRIDGES,
        EdgeStatus.EMPIRICAL,
        0.24,
        proof_cost=1,
    )
    e(
        "qcd.lattice_form_factors",
        "interface.weak_current_inside_hadron",
        EdgeKind.BRIDGES,
        EdgeStatus.COMPUTED,
        0.25,
        proof_cost=3,
    )
    e(
        "qcd.hadron_bound_states",
        "nuclear.chiral_eft_matching",
        EdgeKind.LIMITS_TO,
        EdgeStatus.APPROXIMATE,
        0.35,
        proof_cost=3,
    )
    e(
        "nuclear.chiral_eft_matching",
        "nuclear.many_body_matrix_element",
        EdgeKind.APPROXIMATES,
        EdgeStatus.APPROXIMATE,
        0.48,
        proof_cost=4,
    )
    e(
        "interface.weak_current_inside_hadron",
        "phenomenon.neutron_beta_decay",
        EdgeKind.PROVES,
        EdgeStatus.EMPIRICAL,
        0.25,
        proof_cost=2,
    )
    e(
        "nuclear.many_body_matrix_element",
        "phenomenon.nuclear_beta_decay",
        EdgeKind.PROVES,
        EdgeStatus.APPROXIMATE,
        0.52,
        proof_cost=4,
    )
    e(
        "boundary.radiative_box_corrections",
        "boundary.ckm_first_row_unitarity",
        EdgeKind.BRIDGES,
        EdgeStatus.APPROXIMATE,
        0.40,
        proof_cost=4,
    )
    e(
        "phenomenon.neutron_beta_decay",
        "boundary.ckm_first_row_unitarity",
        EdgeKind.EMPIRICALLY_CONSTRAINS,
        EdgeStatus.EMPIRICAL,
        0.28,
    )
    e(
        "phenomenon.nuclear_beta_decay",
        "boundary.ckm_first_row_unitarity",
        EdgeKind.EMPIRICALLY_CONSTRAINS,
        EdgeStatus.EMPIRICAL,
        0.38,
    )
    e(
        "external.bsm_interface_exclusion",
        "boundary.ckm_first_row_unitarity",
        EdgeKind.BRIDGES,
        EdgeStatus.GAP,
        0.70,
        notes="If Standard Model closure fails, new interactions become candidate external explanations.",
    )
    e(
        "core.quantum_field_theory",
        "boundary.radiative_box_corrections",
        EdgeKind.PROVES,
        EdgeStatus.APPROXIMATE,
        0.38,
        proof_cost=4,
    )
    e(
        "qcd.hadron_bound_states",
        "boundary.radiative_box_corrections",
        EdgeKind.BRIDGES,
        EdgeStatus.APPROXIMATE,
        0.42,
        proof_cost=3,
    )

    return pm


def build_dynamic_cosmology_map() -> ProofMap:
    pm = ProofMap(
        title="Dynamic Cosmological Proof Boundary Map",
        description=(
            "A time-foliated proof-boundary model. The core laws are held fixed in the map, "
            "while the active surface changes as the universe cools, crosses phase transitions, "
            "forms structures, and eventually contains observers capable of building proof maps."
        ),
        metadata={"version": "0.2", "time_unit": "seconds after nominal Big Bang"},
    )

    def n(**kwargs) -> None:
        pm.add_node(Node(**kwargs))

    # Epoch labels; approximate only, used for software demonstration.
    pm.add_epoch(
        Epoch(
            "planck_boundary",
            "Planck / unknown quantum-gravity boundary",
            1e-43,
            "Core-to-cosmology seam is unresolved.",
        )
    )
    pm.add_epoch(
        Epoch(
            "inflation_or_hot_early",
            "Inflation / hot early universe",
            1e-35,
            "Initial-condition and inflation mechanism boundary.",
        )
    )
    pm.add_epoch(
        Epoch(
            "electroweak",
            "Electroweak symmetry-breaking regime",
            1e-12,
            "Effective surface changes as electroweak symmetry breaks.",
        )
    )
    pm.add_epoch(
        Epoch(
            "qcd",
            "QCD confinement / hadronization regime",
            1e-5,
            "Quark-gluon chart transitions to hadron chart.",
        )
    )
    pm.add_epoch(
        Epoch(
            "nucleosynthesis",
            "Big-bang nucleosynthesis",
            180.0,
            "Light nuclei become stable surface objects.",
        )
    )
    pm.add_epoch(
        Epoch(
            "recombination",
            "Recombination / CMB release",
            380000 * YEAR_SECONDS,
            "Atoms form and photons decouple.",
        )
    )
    pm.add_epoch(
        Epoch(
            "stars",
            "Stars and heavy-element production",
            2e8 * YEAR_SECONDS,
            "Stellar free-energy gradients and heavy elements reshape boundary phenomena.",
        )
    )
    pm.add_epoch(
        Epoch(
            "observers",
            "Observers and proof systems",
            13.8e9 * YEAR_SECONDS,
            "Local entropy-exporting systems produce formal maps of the universe.",
        )
    )

    # Core/laws.
    n(
        id="core.quantum_gravity_unknown",
        label="Quantum-gravity core",
        kind=NodeKind.GAP,
        status=NodeStatus.GAP,
        layer=Layer.CORE,
        domain="foundation",
        explanatory_weight=8,
        proof_cost=10,
        uncertainty=0.95,
        statement="A complete proof map needs a quantum-gravity law-kernel or independence result.",
        notes="Kept as a core-adjacent gap to represent the deepest early-universe boundary.",
    )
    n(
        id="core.quantum_field_dynamics",
        label="Quantum field dynamics",
        kind=NodeKind.PRIMITIVE_LAW,
        status=NodeStatus.CORE,
        layer=Layer.CORE,
        domain="foundation",
        explanatory_weight=6,
        proof_cost=4,
        uncertainty=0.12,
        statement="Effective field dynamics for particles and interactions below the quantum-gravity boundary.",
    )
    n(
        id="core.general_relativity",
        label="General relativity / spacetime dynamics",
        kind=NodeKind.PRIMITIVE_LAW,
        status=NodeStatus.CORE,
        layer=Layer.CORE,
        domain="gravity",
        explanatory_weight=6,
        proof_cost=4,
        uncertainty=0.18,
        statement="Classical spacetime dynamics and cosmological expansion at accessible scales.",
    )
    n(
        id="core.statistical_mechanics",
        label="Statistical mechanics",
        kind=NodeKind.PRIMITIVE_LAW,
        status=NodeStatus.CORE,
        layer=Layer.CORE,
        domain="thermodynamics",
        explanatory_weight=5,
        proof_cost=3,
        uncertainty=0.10,
        statement="Coarse-grained entropy, ensembles, irreversibility, and thermodynamic limits.",
    )

    # Early boundary/flow.
    n(
        id="bc.low_entropy_early_state",
        label="Low-entropy early boundary",
        kind=NodeKind.UNCERTAINTY,
        status=NodeStatus.ASSUMPTION,
        layer=Layer.BOUNDARY,
        domain="cosmology",
        explanatory_weight=7,
        proof_cost=5,
        uncertainty=0.70,
        boundary_weight=5,
        epoch_start=0.0,
        epoch_end=1e-30,
        statement="The observed thermodynamic arrow is anchored to a special early low-entropy condition.",
        notes="This is a boundary condition unless derived from the core.",
    )
    n(
        id="flow.entropy_time_orientation",
        label="Entropy/time orientation",
        kind=NodeKind.FLOW,
        status=NodeStatus.PROBABILISTIC,
        layer=Layer.BOUNDARY,
        domain="thermodynamics",
        explanatory_weight=6,
        proof_cost=4,
        uncertainty=0.35,
        boundary_weight=3.5,
        epoch_start=0.0,
        statement="Surface histories acquire orientation through entropy gradients and low-entropy boundary conditions.",
    )
    n(
        id="regime.inflation_or_unknown_initial_expansion",
        label="Inflation or initial expansion mechanism",
        kind=NodeKind.REGIME,
        status=NodeStatus.GAP,
        layer=Layer.BOUNDARY,
        domain="cosmology",
        explanatory_weight=7,
        proof_cost=7,
        uncertainty=0.80,
        boundary_weight=5,
        epoch_start=1e-43,
        epoch_end=1e-30,
        statement="Mechanism explaining the early expansion and initial-condition smoothing remains a boundary gap in this map.",
    )
    n(
        id="regime.hot_plasma",
        label="Hot early plasma",
        kind=NodeKind.REGIME,
        status=NodeStatus.DERIVED,
        layer=Layer.BOUNDARY,
        domain="cosmology",
        explanatory_weight=5,
        proof_cost=3,
        uncertainty=0.25,
        boundary_weight=3,
        epoch_start=1e-35,
        epoch_end=1e-6,
        statement="High-temperature fields/particles dominate the active surface.",
    )

    # Phase transitions/effective surfaces.
    n(
        id="transition.electroweak_symmetry_breaking",
        label="Electroweak symmetry breaking",
        kind=NodeKind.INTERFACE,
        status=NodeStatus.DERIVED,
        layer=Layer.BOUNDARY,
        domain="electroweak",
        explanatory_weight=5,
        proof_cost=3,
        uncertainty=0.25,
        boundary_weight=3,
        epoch_start=1e-12,
        epoch_end=1e-10,
        statement="Electroweak regime folds into photon + massive W/Z low-energy chart.",
    )
    n(
        id="transition.qcd_hadronization",
        label="QCD hadronization",
        kind=NodeKind.INTERFACE,
        status=NodeStatus.APPROXIMATION,
        layer=Layer.BOUNDARY,
        domain="qcd",
        explanatory_weight=6,
        proof_cost=6,
        uncertainty=0.55,
        boundary_weight=4,
        epoch_start=1e-6,
        epoch_end=1e-4,
        statement="Quark-gluon degrees of freedom transition into hadrons; rigorous confinement proof remains a strong-force gap.",
    )
    n(
        id="regime.big_bang_nucleosynthesis",
        label="Big-bang nucleosynthesis",
        kind=NodeKind.REGIME,
        status=NodeStatus.DERIVED,
        layer=Layer.BOUNDARY,
        domain="nuclear",
        explanatory_weight=5,
        proof_cost=4,
        uncertainty=0.25,
        boundary_weight=3,
        epoch_start=1.0,
        epoch_end=1200.0,
        statement="Light nuclei form when temperature/density allow nuclear binding pathways.",
    )
    n(
        id="transition.recombination_cmb",
        label="Recombination / CMB surface",
        kind=NodeKind.OBSERVATION,
        status=NodeStatus.EMPIRICAL,
        layer=Layer.BOUNDARY,
        domain="cosmology",
        explanatory_weight=5,
        proof_cost=3,
        uncertainty=0.18,
        boundary_weight=3,
        epoch_start=200000 * YEAR_SECONDS,
        epoch_end=600000 * YEAR_SECONDS,
        statement="Atoms form and photons decouple, creating a major observational boundary surface.",
    )
    n(
        id="regime.structure_formation",
        label="Structure formation",
        kind=NodeKind.REGIME,
        status=NodeStatus.COMPUTED,
        layer=Layer.BOUNDARY,
        domain="gravity",
        explanatory_weight=5,
        proof_cost=5,
        uncertainty=0.28,
        boundary_weight=3,
        epoch_start=1e6 * YEAR_SECONDS,
        statement="Gravity amplifies density fluctuations into cosmic web, galaxies, and large-scale structure.",
    )
    n(
        id="regime.stellar_free_energy",
        label="Stellar free-energy currents",
        kind=NodeKind.FLOW,
        status=NodeStatus.DERIVED,
        layer=Layer.BOUNDARY,
        domain="astrophysics",
        explanatory_weight=5,
        proof_cost=4,
        uncertainty=0.20,
        boundary_weight=3,
        epoch_start=1e8 * YEAR_SECONDS,
        statement="Stars create long-lived energy gradients and synthesize heavier elements.",
    )
    n(
        id="regime.chemistry",
        label="Chemical complexity",
        kind=NodeKind.REGIME,
        status=NodeStatus.DERIVED,
        layer=Layer.BOUNDARY,
        domain="chemistry",
        explanatory_weight=4,
        proof_cost=4,
        uncertainty=0.18,
        boundary_weight=2.5,
        epoch_start=2e8 * YEAR_SECONDS,
        statement="Atoms and molecules create new effective surface rules.",
    )
    n(
        id="regime.self_organized_observers",
        label="Self-organized observers",
        kind=NodeKind.PHENOMENON,
        status=NodeStatus.EMPIRICAL,
        layer=Layer.BOUNDARY,
        domain="observers",
        explanatory_weight=5,
        proof_cost=6,
        uncertainty=0.45,
        boundary_weight=4,
        epoch_start=8e9 * YEAR_SECONDS,
        statement="Local entropy-exporting systems form models, records, measurements, and proofs.",
    )
    n(
        id="regime.formal_proof_maps",
        label="Formal proof maps",
        kind=NodeKind.MODEL,
        status=NodeStatus.DERIVED,
        layer=Layer.BOUNDARY,
        domain="metascience",
        explanatory_weight=4,
        proof_cost=5,
        uncertainty=0.40,
        boundary_weight=3,
        epoch_start=13.8e9 * YEAR_SECONDS,
        statement="The universe contains subsystems that formalize parts of the universe into proof graphs.",
    )

    # Interior bridge principles.
    n(
        id="bridge.effective_field_theory",
        label="Effective field theory charts",
        kind=NodeKind.BRIDGE,
        status=NodeStatus.DERIVED,
        layer=Layer.INTERIOR,
        domain="foundation",
        explanatory_weight=5,
        proof_cost=4,
        uncertainty=0.20,
        statement="Different energy regimes are covered by local descriptions glued by matching/limit relations.",
    )
    n(
        id="bridge.renormalization_group_flow",
        label="Renormalization-scale flow",
        kind=NodeKind.BRIDGE,
        status=NodeStatus.DERIVED,
        layer=Layer.INTERIOR,
        domain="foundation",
        explanatory_weight=5,
        proof_cost=4,
        uncertainty=0.20,
        statement="Parameters/descriptions change with energy scale, giving shell-to-shell proof flow.",
    )
    n(
        id="bridge.noether_conservation",
        label="Symmetry → conservation bridges",
        kind=NodeKind.THEOREM,
        status=NodeStatus.PROVED,
        layer=Layer.INTERIOR,
        domain="foundation",
        explanatory_weight=4,
        proof_cost=3,
        uncertainty=0.08,
        statement="Symmetries constrain permitted surface flows via conservation laws.",
    )

    def e(
        source: str,
        target: str,
        kind=EdgeKind.PROVES,
        status=EdgeStatus.ACTIVE,
        uncertainty=0.1,
        weight=1.0,
        proof_cost=1.0,
        notes="",
    ) -> None:
        pm.add_edge(
            Edge(
                source=source,
                target=target,
                kind=kind,
                status=status,
                uncertainty=uncertainty,
                weight=weight,
                proof_cost=proof_cost,
                notes=notes,
            )
        )

    # Core to bridges.
    e(
        "core.quantum_field_dynamics",
        "bridge.effective_field_theory",
        EdgeKind.PROVES,
        EdgeStatus.ACTIVE,
        0.18,
        proof_cost=3,
    )
    e(
        "core.quantum_field_dynamics",
        "bridge.renormalization_group_flow",
        EdgeKind.PROVES,
        EdgeStatus.ACTIVE,
        0.18,
        proof_cost=3,
    )
    e(
        "core.quantum_field_dynamics",
        "bridge.noether_conservation",
        EdgeKind.PROVES,
        EdgeStatus.PROVED,
        0.08,
        proof_cost=2,
    )
    e(
        "core.statistical_mechanics",
        "flow.entropy_time_orientation",
        EdgeKind.PROVES,
        EdgeStatus.APPROXIMATE,
        0.35,
        proof_cost=3,
    )
    e(
        "bc.low_entropy_early_state",
        "flow.entropy_time_orientation",
        EdgeKind.BRIDGES,
        EdgeStatus.ASSUMED,
        0.60,
        notes="Low-entropy initial condition or boundary condition supplies time orientation.",
    )
    e(
        "core.general_relativity",
        "regime.inflation_or_unknown_initial_expansion",
        EdgeKind.BRIDGES,
        EdgeStatus.GAP,
        0.80,
    )
    e(
        "core.quantum_gravity_unknown",
        "regime.inflation_or_unknown_initial_expansion",
        EdgeKind.BLOCKS,
        EdgeStatus.GAP,
        0.95,
    )
    e(
        "regime.inflation_or_unknown_initial_expansion",
        "bc.low_entropy_early_state",
        EdgeKind.BRIDGES,
        EdgeStatus.ASSUMED,
        0.75,
    )
    e(
        "regime.inflation_or_unknown_initial_expansion",
        "regime.hot_plasma",
        EdgeKind.FLOWS_TO,
        EdgeStatus.ASSUMED,
        0.55,
    )
    e("core.quantum_field_dynamics", "regime.hot_plasma", EdgeKind.PROVES, EdgeStatus.ACTIVE, 0.25)
    e(
        "bridge.effective_field_theory",
        "transition.electroweak_symmetry_breaking",
        EdgeKind.BRIDGES,
        EdgeStatus.ACTIVE,
        0.25,
        proof_cost=2,
    )
    e(
        "regime.hot_plasma",
        "transition.electroweak_symmetry_breaking",
        EdgeKind.FLOWS_TO,
        EdgeStatus.ACTIVE,
        0.25,
    )
    e(
        "bridge.renormalization_group_flow",
        "transition.qcd_hadronization",
        EdgeKind.BRIDGES,
        EdgeStatus.APPROXIMATE,
        0.50,
        proof_cost=3,
    )
    e(
        "transition.electroweak_symmetry_breaking",
        "transition.qcd_hadronization",
        EdgeKind.FLOWS_TO,
        EdgeStatus.ACTIVE,
        0.30,
    )
    e(
        "transition.qcd_hadronization",
        "regime.big_bang_nucleosynthesis",
        EdgeKind.FLOWS_TO,
        EdgeStatus.APPROXIMATE,
        0.40,
    )
    e(
        "bridge.noether_conservation",
        "regime.big_bang_nucleosynthesis",
        EdgeKind.PROVES,
        EdgeStatus.ACTIVE,
        0.20,
    )
    e(
        "regime.big_bang_nucleosynthesis",
        "transition.recombination_cmb",
        EdgeKind.FLOWS_TO,
        EdgeStatus.ACTIVE,
        0.22,
    )
    e(
        "core.general_relativity",
        "regime.structure_formation",
        EdgeKind.PROVES,
        EdgeStatus.COMPUTED,
        0.25,
        proof_cost=4,
    )
    e(
        "transition.recombination_cmb",
        "regime.structure_formation",
        EdgeKind.FLOWS_TO,
        EdgeStatus.EMPIRICAL,
        0.25,
    )
    e(
        "regime.structure_formation",
        "regime.stellar_free_energy",
        EdgeKind.FLOWS_TO,
        EdgeStatus.COMPUTED,
        0.25,
    )
    e("regime.stellar_free_energy", "regime.chemistry", EdgeKind.FLOWS_TO, EdgeStatus.ACTIVE, 0.20)
    e(
        "regime.chemistry",
        "regime.self_organized_observers",
        EdgeKind.FLOWS_TO,
        EdgeStatus.EMPIRICAL,
        0.45,
        notes="Abiogenesis/cognition remains an emergent complex-systems boundary, not a closed proof.",
    )
    e(
        "regime.self_organized_observers",
        "regime.formal_proof_maps",
        EdgeKind.FLOWS_TO,
        EdgeStatus.ACTIVE,
        0.40,
    )
    e(
        "flow.entropy_time_orientation",
        "regime.stellar_free_energy",
        EdgeKind.BRIDGES,
        EdgeStatus.ACTIVE,
        0.25,
    )
    e(
        "flow.entropy_time_orientation",
        "regime.self_organized_observers",
        EdgeKind.BRIDGES,
        EdgeStatus.APPROXIMATE,
        0.45,
    )

    return pm
