"""Curated teaching map: Newtonian gravity as a regime of general relativity.

This is a source-backed example, not a formal proof or a new evidence acceptance.
"""

from .model import Edge, Node, ProofMap

SOURCES = {
    "einstein": {
        "title": "Albert Einstein, Relativity: The Special and General Theory (1916)",
        "url": "https://www.gutenberg.org/files/5001/5001-h/5001-h.htm",
        "sections": "Parts I-II; Appendix III",
    },
    "newton-limit": {
        "title": "Edoardo Milotti, The Newtonian limit (2025)",
        "url": "https://wwwusers.ts.infn.it/~milotti/Didattica/GravitationalWaves/handouts/11-NewtonianLimit.pdf",
        "sections": "Sections 1-2",
    },
    "light": {
        "title": "Steven S. Shapiro and Irwin I. Shapiro, Gravitational deflection of light",
        "url": "https://www.einstein-online.info/en/spotlight/light_deflection/",
        "sections": "Light deflection in general relativity",
    },
    "tests": {
        "title": "Stanford Gravity Probe B, Testing Einstein",
        "url": "https://einstein.stanford.edu/SPACETIME/spacetime3.html",
        "sections": "Equivalence principle; Mercury's perihelion shift",
    },
}
SOURCES.update(
    {
        "jacobson-1995": {
            "title": "Ted Jacobson, Thermodynamics of Spacetime (1995)",
            "url": "https://arxiv.org/abs/gr-qc/9504004",
            "sections": "Local Rindler horizons, equilibrium and equation-of-state argument",
        },
        "verlinde-2011": {
            "title": "Erik Verlinde, On the Origin of Gravity and the Laws of Newton (2010 preprint; 2011 journal)",
            "url": "https://arxiv.org/abs/1001.0785",
            "sections": "Sections 3-5: holographic screens, equipartition and proposed recovery",
        },
        "verlinde-2016": {
            "title": "Erik Verlinde, Emergent Gravity and the Dark Universe (2016 preprint; 2017 journal)",
            "url": "https://arxiv.org/abs/1611.02269",
            "sections": "de Sitter entropy and proposed elastic response",
        },
    }
)


def build_gravity_transition_map() -> ProofMap:
    """Return the pedagogical regime-transition fixture; no verification authority."""
    pm = ProofMap(
        title="Newton to Einstein: a change of regime",
        description=(
            "Newtonian gravity remains a controlled approximation, not a discarded theory. "
            "Special relativity changes spacetime kinematics; general relativity describes gravity. "
            "Follow the explicit assumptions connecting general relativity to the Newtonian limit."
        ),
        metadata={
            "purpose": "curated_pedagogical_regime_transition",
            "accepted_claims": 0,
            "formal_verification": "NOT_RUN",
            "sources": SOURCES,
            "numeric_uncertainty": "Required schema placeholder 0; NOT_ASSESSED, not confidence.",
            "edge_semantics": "Explanatory links and approximation relations, not verified proofs.",
            "guided_path": [
                "newton.gravity",
                "sr.kinematics",
                "equivalence.local",
                "gr.geometry",
                "gr.field_equations",
                "regime.newtonian",
                "bridge.geodesic",
                "bridge.poisson",
                "newton.gravity",
                "boundary.mercury",
                "boundary.light",
            ],
        },
    )

    def node(
        ident: str,
        label: str,
        kind: str,
        status: str,
        layer: str,
        statement: str,
        sources: list[str],
        regime: str = "",
    ) -> None:
        pm.add_node(
            Node(
                id=ident,
                label=label,
                kind=kind,
                status=status,
                layer=layer,
                domain="Gravitation and relativity",
                statement=statement,
                source_ids=sources,
                evidence_class="CURATED_SOURCE_SUMMARY",
                validity_regime=regime,
                uncertainty_kind="NOT_ASSESSED",
                formalization_status="not_formalized",
                notes="Illustrative authored claim; no formal verification or acceptance by this map.",
            )
        )

    node(
        "newton.gravity",
        "Newtonian gravitation",
        "MODEL",
        "APPROXIMATION",
        "CORE",
        "A potential obeying Laplacian(Phi)=4*pi*G*rho gives test-body acceleration a=-grad(Phi). "
        "For an isolated spherical source, Phi=-GM/r outside it.",
        ["newton-limit"],
        "Classical gravitational model; recovered under the stated Newtonian-limit assumptions.",
    )
    node(
        "newton.kinematics",
        "Absolute-time kinematics",
        "MODEL",
        "ASSUMPTION",
        "CORE",
        "Newtonian mechanics uses absolute time and Galilean kinematics; these are low-speed approximations, not universal spacetime structure.",
        ["einstein"],
        "Low relative velocities compared with c.",
    )
    node(
        "sr.kinematics",
        "Special relativity: not a gravity theory",
        "MODEL",
        "EXTERNAL",
        "INTERIOR",
        "Special relativity uses Lorentz symmetry and Minkowski spacetime. It is not by itself a theory of gravitation; its local inertial physics is retained in GR.",
        ["einstein"],
        "Flat spacetime, or sufficiently small freely falling laboratories in GR.",
    )
    node(
        "equivalence.local",
        "Local equivalence principle",
        "PRIMITIVE_LAW",
        "ASSUMPTION",
        "CORE",
        "Freely falling local experiments motivate equivalence with an inertial laboratory. This is local: tidal effects cannot in general be removed over a finite region.",
        ["einstein", "tests"],
    )
    node(
        "gr.geometry",
        "General relativity: dynamical geometry",
        "MODEL",
        "EXTERNAL",
        "INTERIOR",
        "Gravity is described by curved spacetime. Freely falling test bodies follow geodesics; curvature encodes tidal effects.",
        ["einstein", "newton-limit"],
        "Classical spacetime description; not a quantum-gravity completion.",
    )
    node(
        "gr.field_equations",
        "Einstein field equations",
        "PRIMITIVE_LAW",
        "ASSUMPTION",
        "INTERIOR",
        "Einstein's field equations relate spacetime curvature to stress-energy. Recovering Newtonian gravity requires source and regime assumptions, not merely renaming a force.",
        ["newton-limit", "einstein"],
    )
    node(
        "regime.newtonian",
        "Weak, slow, nearly static regime",
        "REGIME",
        "ASSUMPTION",
        "BOUNDARY",
        "Require |Phi|/c^2 much less than 1, v/c much less than 1, nearly static fields, nonrelativistic sources with negligible pressure/stress versus rho*c^2, and negligible cosmological-constant effects.",
        ["newton-limit"],
        "Leading-order Newtonian approximation; a small correction may still be measurable.",
    )
    node(
        "bridge.geodesic",
        "Geodesics recover Newton's acceleration",
        "BRIDGE",
        "APPROXIMATION",
        "INTERIOR",
        "With signature (-,+,+,+), g00 approximately -(1+2*Phi/c^2). For slow test bodies in a static weak field, the geodesic equation gives a approximately -grad(Phi).",
        ["newton-limit"],
        "Neglect higher-order velocity and potential corrections.",
    )
    node(
        "bridge.poisson",
        "Field equations recover Poisson's equation",
        "BRIDGE",
        "APPROXIMATION",
        "INTERIOR",
        "For the same weak, static regime and matter dominated by rest-mass density, the Einstein equations reduce to Laplacian(Phi)=4*pi*G*rho.",
        ["newton-limit"],
        "Negligible pressure/stress, cosmological term and higher-order corrections.",
    )
    node(
        "regime.post_newtonian",
        "Precision boundary: post-Newtonian terms",
        "REGIME",
        "APPROXIMATION",
        "BOUNDARY",
        "Weak fields do not make every relativistic correction irrelevant. Precision orbital and light-propagation measurements can distinguish GR from leading-order Newtonian predictions.",
        ["tests", "light"],
        "Weak field with relativistic corrections retained; light is not a slow test body.",
    )
    node(
        "boundary.mercury",
        "Mercury: residual perihelion advance",
        "OBSERVATION",
        "EMPIRICAL",
        "BOUNDARY",
        "GR accounts for roughly 43 arcseconds per century of Mercury's perihelion advance left after known Newtonian perturbations are included; this is not the total precession.",
        ["einstein", "tests"],
        "Solar-system precision test; not a machine-checked result in this map.",
    )
    node(
        "boundary.light",
        "Light bending: outside the slow-body limit",
        "PHENOMENON",
        "EXTERNAL",
        "BOUNDARY",
        "For a weak spherical lens, GR predicts leading deflection 4GM/(b*c^2). A Newtonian corpuscular calculation gives half this value; it is a historical comparison, not Newton's complete theory of light.",
        ["light"],
        "Weak lens, distant source/observer, impact parameter b; photons have v=c.",
    )
    node(
        "boundary.tides",
        "Local inertial frames do not erase tides",
        "INTERFACE",
        "EXTERNAL",
        "BOUNDARY",
        "Local removal of gravitational acceleration does not remove curvature or relative acceleration of neighboring geodesics. Local SR does not imply globally flat spacetime.",
        ["einstein", "tests"],
    )
    node(
        "limit.classical",
        "Classical theory is not final completion",
        "GAP",
        "GAP",
        "EXTERIOR",
        "This transition does not settle quantum gravity or singularity resolution. The map deliberately leaves those domains outside its explanatory closure.",
        ["tests"],
        "Outside the scope of this classical pedagogical example.",
    )

    node(
        "gap.mercury",
        "Newtonian precision gap: Mercury residual",
        "GAP",
        "GAP",
        "BOUNDARY",
        "Obligation: explain the residual perihelion advance after known Newtonian perturbations, not the total precession or an arbitrary fitted correction.",
        ["tests", "einstein"],
        "An explanatory gap in the specified Newtonian model.",
    )
    node(
        "gap.causality",
        "Compatibility gap: instantaneous interaction",
        "GAP",
        "GAP",
        "BOUNDARY",
        "The instantaneous Newtonian potential is not a fundamental Lorentz-covariant account of changing interactions. Obligation: construct a causal relativistic extension while preserving quasi-static successes.",
        ["einstein"],
        "Framework compatibility tension; static calculations need not fail.",
    )
    node(
        "gap.light",
        "Domain gap: light and gravity",
        "GAP",
        "GAP",
        "BOUNDARY",
        "A slow massive-test-body limit does not predict null-ray propagation. Obligation: specify light's gravitational coupling and compare deflection with observations; the historical corpuscular analogy is not a complete relativistic theory.",
        ["light"],
        "Weak field alone is insufficient for the slow-body approximation.",
    )

    node(
        "entropy.jacobson_assumptions",
        "Jacobson: local-horizon thermodynamic assumptions",
        "REGIME",
        "ASSUMPTION",
        "BOUNDARY",
        "Assume horizon entropy proportional to area, local equilibrium, Clausius heat balance delta Q=T*dS for all local Rindler horizons, and matching accelerated-observer energy flux and Unruh temperature.",
        ["jacobson-1995"],
        "Local equilibrium and continuum scale separation; not an arbitrary entropy formula.",
    )
    node(
        "entropy.jacobson",
        "Jacobson: Einstein equation as equation of state",
        "MODEL",
        "EXTERNAL",
        "INTERIOR",
        "Jacobson's conditional thermodynamic argument recovers the Einstein equation under its horizon assumptions. It interprets GR rather than demonstrating a distinct observed replacement or specifying microscopic constituents.",
        ["jacobson-1995"],
        "Research interpretation; not formally checked by this map.",
    )
    node(
        "entropy.verlinde2011",
        "Verlinde 2011: entropic-force proposal",
        "MODEL",
        "EXTERNAL",
        "BOUNDARY",
        "A separate proposal uses holographic screens, entropy changes with displacement, an area-based count of degrees of freedom and equipartition to recover Newtonian gravity, with a proposed relativistic extension.",
        ["verlinde-2011"],
        "Conditional holographic/equipartition construction, not an established replacement for GR.",
    )
    node(
        "entropy.verlinde2016",
        "Verlinde 2016: emergent dark-gravity proposal",
        "MODEL",
        "EXTERNAL",
        "BOUNDARY",
        "A later, distinct proposal invokes de Sitter horizon entropy, a volume-law contribution and an elastic response to matter-induced entropy displacement, proposing additional apparent-dark-matter effects.",
        ["verlinde-2016"],
        "Research proposal with restricted assumptions; not proof that dark matter is unnecessary.",
    )
    node(
        "entropy.gap_microphysics",
        "Open obligation: microscopic and nonequilibrium account",
        "GAP",
        "GAP",
        "EXTERIOR",
        "Specify microscopic states, justify the entropy law and applicable equilibrium limit, and establish behavior beyond those assumptions. Recovering a known equation alone does not complete quantum gravity.",
        ["jacobson-1995", "verlinde-2011"],
        "Research evaluation obligation; no closure claimed.",
    )
    node(
        "entropy.gap_tests",
        "Open obligation: discriminating predictions",
        "GAP",
        "GAP",
        "EXTERIOR",
        "Separate reinterpretation from predictions different from GR plus matter. Specify a complete applicable model and compare dynamics, lensing and cosmology with independent data and uncertainties before claiming replacement.",
        ["verlinde-2016", "verlinde-2011"],
        "No data fitting, model ranking or empirical acceptance executed in this example.",
    )

    def edge(source: str, target: str, kind: str, statement: str, sources: list[str]) -> None:
        pm.add_edge(
            Edge(
                source,
                target,
                kind=kind,
                status="APPROXIMATE" if kind in {"LIMITS_TO", "APPROXIMATES"} else "ASSUMED",
                statement=statement,
                source_ids=sources,
                uncertainty_kind="NOT_ASSESSED",
                evidence_class="CURATED_EXPLANATORY_RELATION",
                formalization_status="not_formalized",
                notes="Not a formal derivation or evidence-acceptance event.",
            )
        )

    edge(
        "newton.kinematics",
        "newton.gravity",
        "DEPENDS_ON",
        "Newtonian dynamics uses its classical kinematic setting.",
        ["einstein"],
    )
    edge(
        "sr.kinematics",
        "newton.kinematics",
        "LIMITS_TO",
        "Low-speed Lorentz kinematics approaches Galilean kinematics.",
        ["einstein"],
    )
    edge(
        "equivalence.local",
        "gr.geometry",
        "BRIDGES",
        "Local equivalence motivates, but alone does not uniquely derive, GR.",
        ["einstein"],
    )
    edge(
        "sr.kinematics",
        "gr.geometry",
        "INTERFACE",
        "GR retains local special-relativistic physics, not a globally Minkowski metric.",
        ["einstein"],
    )
    edge(
        "gr.field_equations",
        "gr.geometry",
        "DEFINES",
        "The field equations constrain the dynamical metric with matter sources.",
        ["einstein"],
    )
    edge(
        "gr.geometry",
        "bridge.geodesic",
        "LIMITS_TO",
        "Geodesic motion has a Newtonian leading-order limit only with the regime assumptions.",
        ["newton-limit"],
    )
    edge(
        "regime.newtonian",
        "bridge.geodesic",
        "DEPENDS_ON",
        "Weak, static field and slow test-body assumptions are required.",
        ["newton-limit"],
    )
    edge(
        "gr.field_equations",
        "bridge.poisson",
        "LIMITS_TO",
        "The field equations reduce to the Newtonian source equation in the specified regime.",
        ["newton-limit"],
    )
    edge(
        "regime.newtonian",
        "bridge.poisson",
        "DEPENDS_ON",
        "Rest-mass dominance and weak static field are required.",
        ["newton-limit"],
    )
    edge(
        "bridge.geodesic",
        "newton.gravity",
        "APPROXIMATES",
        "Recovers the acceleration equation, not the entire theory on its own.",
        ["newton-limit"],
    )
    edge(
        "bridge.poisson",
        "newton.gravity",
        "APPROXIMATES",
        "Recovers the potential source equation, completing the leading-order bridge.",
        ["newton-limit"],
    )
    edge(
        "gr.geometry",
        "regime.post_newtonian",
        "INTERFACE",
        "Small curvature corrections can matter for precision observations.",
        ["tests"],
    )
    edge(
        "regime.post_newtonian",
        "boundary.mercury",
        "BRIDGES",
        "Relativistic corrections account for the residual orbital advance.",
        ["tests"],
    )
    edge(
        "gr.geometry",
        "boundary.light",
        "BRIDGES",
        "Null-geodesic light propagation is not the slow massive-particle limit.",
        ["light"],
    )
    edge(
        "regime.post_newtonian",
        "boundary.light",
        "INTERFACE",
        "Weak-field light deflection retains relativistic spatial geometry.",
        ["light"],
    )
    edge(
        "boundary.mercury",
        "newton.gravity",
        "EMPIRICALLY_CONSTRAINS",
        "Residual observations constrain precision use of the leading-order approximation.",
        ["tests"],
    )
    edge(
        "gr.geometry",
        "boundary.tides",
        "DEFINES",
        "Curvature remains despite a locally inertial coordinate choice.",
        ["einstein"],
    )
    edge(
        "boundary.tides",
        "sr.kinematics",
        "INTERFACE",
        "Local inertial approximation is not a global removal of gravity.",
        ["einstein"],
    )
    edge(
        "gr.geometry",
        "limit.classical",
        "INTERFACE",
        "Classical explanatory scope does not close quantum/singularity questions.",
        ["tests"],
    )
    edge(
        "newton.gravity",
        "gap.mercury",
        "INTERFACE",
        "Expose the unmet precision obligation.",
        ["tests"],
    )
    edge(
        "boundary.mercury",
        "gap.mercury",
        "EMPIRICALLY_CONSTRAINS",
        "The residual supplies a testable requirement.",
        ["tests"],
    )
    edge(
        "newton.gravity",
        "gap.causality",
        "INTERFACE",
        "Quasi-static potential leaves relativistic dynamics unspecified.",
        ["einstein"],
    )
    edge(
        "sr.kinematics",
        "gap.causality",
        "INTERFACE",
        "Relativistic causality constrains extensions.",
        ["einstein"],
    )
    edge(
        "newton.gravity",
        "gap.light",
        "INTERFACE",
        "Photons require a new propagation bridge.",
        ["light"],
    )
    edge(
        "boundary.light",
        "gap.light",
        "EMPIRICALLY_CONSTRAINS",
        "Deflection distinguishes propagation laws.",
        ["light"],
    )
    edge(
        "gap.mercury",
        "gr.geometry",
        "BRIDGES",
        "Curated candidate response: relativistic orbital dynamics, not an inference proving GR.",
        ["tests"],
    )
    edge(
        "gap.causality",
        "gr.field_equations",
        "BRIDGES",
        "Curated candidate response: dynamical spacetime with relativistic causal structure.",
        ["einstein"],
    )
    edge(
        "gap.light",
        "gr.geometry",
        "BRIDGES",
        "Curated candidate response: null geodesics in shared geometry.",
        ["light"],
    )
    pm.metadata["boundary_walkthrough"] = [
        {
            "id": "scope",
            "title": "1. State what Newton actually closes",
            "detail": "Fix the explanatory target and assumptions before identifying gaps.",
            "node_ids": ["newton.gravity", "newton.kinematics", "regime.newtonian"],
            "question": "Which phenomena and precision are covered?",
            "evidence": "Successful weak-field, slow-motion behavior is the baseline, not discarded evidence.",
            "action": "Record kinematics, quasi-static potential, matter assumptions and required precision.",
            "outcome": "A scoped Newtonian explanatory region, not universal closure.",
            "source_ids": ["newton-limit", "einstein"],
        },
        {
            "id": "frontier",
            "title": "2. Expose boundary obligations",
            "detail": "Separate a residual, a compatibility tension and an out-of-regime probe.",
            "node_ids": [
                "gap.mercury",
                "gap.causality",
                "gap.light",
                "boundary.mercury",
                "boundary.light",
            ],
            "question": "What is unexplained, incompatible or outside the assumptions?",
            "evidence": "Mercury's residual, relativistic causality and light deflection impose different constraints.",
            "action": "Create sourced obligations, without treating them as proof of a preferred replacement.",
            "outcome": "Three authored frontier gaps, not a computed probability or theorem-discovery result.",
            "source_ids": ["tests", "einstein", "light"],
        },
        {
            "id": "diagnose",
            "title": "3. Trace gaps back to assumptions",
            "detail": "Distinguish approximation limits from the need for a broader framework.",
            "node_ids": [
                "gap.mercury",
                "gap.causality",
                "gap.light",
                "newton.kinematics",
                "regime.post_newtonian",
                "sr.kinematics",
            ],
            "question": "Which missing bridge or assumption blocks the target?",
            "evidence": "The slow-body limit excludes photons; leading-order dynamics omits precision corrections; instantaneous interaction lacks relativistic causal dynamics.",
            "action": "Link obligations to assumptions; compare alternatives and observational/systematic uncertainty.",
            "outcome": "A constrained extension problem. The constraints do not uniquely determine Einstein's equations.",
            "source_ids": ["einstein", "newton-limit", "light", "tests"],
        },
        {
            "id": "candidate",
            "title": "4. Introduce GR as a candidate bridge",
            "detail": "One dynamical geometry connects massive bodies, light and local relativistic physics.",
            "node_ids": [
                "equivalence.local",
                "gr.geometry",
                "gr.field_equations",
                "boundary.tides",
            ],
            "question": "Can a shared extension address the obligations without incompatible patches?",
            "evidence": "Equivalence motivates geometry, but neither it nor this graph uniquely derives GR.",
            "action": "Specify equations, coupling and propagation, then independently derive testable predictions.",
            "outcome": "A documented candidate extension, not proof acceptance or algorithmic invention of GR.",
            "source_ids": ["einstein", "tests"],
        },
        {
            "id": "test",
            "title": "5. Demand new coverage and old-limit recovery",
            "detail": "Meet frontier tests while preserving the old theory's successful regime.",
            "node_ids": [
                "boundary.mercury",
                "boundary.light",
                "bridge.geodesic",
                "bridge.poisson",
                "regime.newtonian",
            ],
            "question": "Does the candidate address the residuals and recover Newton under explicit conditions?",
            "evidence": "Sources describe Mercury/light tests and both Newtonian bridges. This app has not executed their derivations or fitted data.",
            "action": "Check new predictions, field and motion limits, assumptions, data quality and alternatives.",
            "outcome": "Source-backed support with open verification obligations, not a numerical test run or formal acceptance.",
            "source_ids": ["tests", "light", "newton-limit"],
        },
        {
            "id": "collapse",
            "title": "6. Reorganize gaps under the broader explanation",
            "detail": "Collapse means curated explanatory reorganization, retaining Newton as a regime-limited approximation.",
            "node_ids": [
                "gr.geometry",
                "gr.field_equations",
                "bridge.geodesic",
                "bridge.poisson",
                "newton.gravity",
                "limit.classical",
            ],
            "question": "Which obligations share an explanation, and which boundaries remain?",
            "evidence": "The relativistic framework addresses the curated classical tensions and recovers Newton's regime; quantum and singularity questions remain outside closure.",
            "action": "Retain Newton's successes, organize the tensions under the candidate framework, and preserve unresolved validation and scope limits.",
            "outcome": "Explanatory reorganization and regime recovery only. The graph cannot derive GR, prove it unique, or grant proof acceptance.",
            "source_ids": ["einstein", "newton-limit", "tests"],
        },
    ]
    edge(
        "entropy.jacobson_assumptions",
        "entropy.jacobson",
        "DEPENDS_ON",
        "Conditional thermodynamic argument requires these assumptions.",
        ["jacobson-1995"],
    )
    edge(
        "entropy.jacobson",
        "gr.field_equations",
        "BRIDGES",
        "Equation-of-state interpretation, not an additional observed force.",
        ["jacobson-1995"],
    )
    edge(
        "entropy.verlinde2011",
        "newton.gravity",
        "BRIDGES",
        "Proposed recovery under screen and equipartition assumptions.",
        ["verlinde-2011"],
    )
    edge(
        "entropy.verlinde2011",
        "entropy.verlinde2016",
        "INTERFACE",
        "Related author/program, but distinct assumptions and claims; not logical implication.",
        ["verlinde-2011", "verlinde-2016"],
    )
    edge(
        "entropy.jacobson",
        "entropy.gap_microphysics",
        "INTERFACE",
        "Macroscopic recovery leaves microscopic explanation open.",
        ["jacobson-1995"],
    )
    edge(
        "entropy.verlinde2011",
        "entropy.gap_microphysics",
        "INTERFACE",
        "Audit the proposed screen degrees of freedom and limits.",
        ["verlinde-2011"],
    )
    edge(
        "entropy.verlinde2016",
        "entropy.gap_tests",
        "INTERFACE",
        "Proposed additional effects require discriminating empirical tests.",
        ["verlinde-2016"],
    )
    edge(
        "entropy.gap_tests",
        "gr.geometry",
        "INTERFACE",
        "Compare with the existing relativistic baseline; no automatic replacement.",
        ["verlinde-2016", "tests"],
    )
    pm.metadata["boundary_walkthrough"].extend(
        [
            {
                "id": "entropy-frameworks",
                "title": "7. Distinguish entropy-based approaches",
                "detail": "Thermodynamic interpretation, entropic force and emergent dark gravity are not one theory.",
                "node_ids": [
                    "entropy.jacobson",
                    "entropy.verlinde2011",
                    "entropy.verlinde2016",
                    "gr.field_equations",
                ],
                "question": "Is this a conditional recovery of known equations or a new empirical claim?",
                "evidence": "The three primary papers make different constructions and claims; agreement with GR equations does not itself distinguish their ontology.",
                "action": "Keep separate assumption sets, recovered limits and proposed deviations.",
                "outcome": "Three research branches, not a sequentially established successor to Einstein.",
                "source_ids": ["jacobson-1995", "verlinde-2011", "verlinde-2016"],
            },
            {
                "id": "entropy-assumptions",
                "title": "8. Expose the entropy proof boundary",
                "detail": "Move the audit upstream to the entropy law, local equilibrium and proposed microscopic degrees of freedom.",
                "node_ids": [
                    "entropy.jacobson_assumptions",
                    "entropy.jacobson",
                    "entropy.verlinde2011",
                    "entropy.gap_microphysics",
                ],
                "question": "Which assumptions replace unexplained gravitational structure, and are they independently justified?",
                "evidence": "Local-horizon Clausius balance differs from the screen/equipartition construction.",
                "action": "Check scale separation, nonequilibrium extensions, microscopic realization and whether recovery assumes equivalent information.",
                "outcome": "Explicit conditional bridges and open research obligations; no microscopic theory or proof supplied by this graph.",
                "source_ids": ["jacobson-1995", "verlinde-2011"],
            },
            {
                "id": "entropy-tests",
                "title": "9. Require discrimination before another collapse",
                "detail": "Explanatory elegance alone cannot justify promoting an entropy proposal over GR.",
                "node_ids": [
                    "entropy.verlinde2016",
                    "entropy.gap_tests",
                    "gr.geometry",
                    "newton.gravity",
                    "limit.classical",
                ],
                "question": "What observation differs, under which regime, and with what competing explanations?",
                "evidence": "The later emergent-gravity proposal motivates additional effects; this example does not fit or validate them.",
                "action": "Specify predictions, compare independent dynamics/lensing/cosmology data, retain successful Newton/GR limits and record unresolved assumptions.",
                "outcome": "Research hypotheses remain open. No further collapse, empirical victory, formal acceptance or dark-matter elimination is asserted.",
                "source_ids": ["verlinde-2016", "verlinde-2011", "jacobson-1995"],
            },
        ]
    )
    pm.metadata["entropy_scope"] = "DISTINCT_RESEARCH_PROPOSALS_NOT_ESTABLISHED_REPLACEMENT"
    pm.metadata["collapse_semantics"] = "CURATED_EXPLANATORY_REORGANIZATION_NOT_FORMAL_PROOF"
    return pm
