# Original regression corpus

`golden.json` contains expected labels authored from each fixture's source and
intended supported behavior. The benchmark reads those labels; it never derives
the expected answer by running the parser. Development (`train`) and held-out
regression families remain distinct. These finite, synthetic cases are not a
sample from the population of mathematical papers.

The corpus includes the twelve original alpha categories. Category membership
is an inventory of cases, not evidence that every associated capability passed.
Positive/negative tests and installed execution scenarios qualify the capabilities.
Each paper has provenance, declared roles, statement/proof/dependency labels and
any additional independently labelled dimensions. An absent metric label means
unknown; an explicitly empty label set means that no positive item is expected.

The PDF files are existing repository-generated born-digital and scan fixtures.
The reflexivity paper is an original synthetic example. `agoh_synthetic.tex` is
an explicitly adapted illustration of repository artifacts, not Agoh's original
manuscript, autonomous rediscovery, or a novelty claim. No third-party manuscript
is incorporated by this corpus expansion and no repository license is changed.

`semantic_interpretations.tex` has separately authored canned provider outputs
and expected evaluation labels. The benchmark actually runs decomposition,
independent advisory fidelity checking and validated response replay through the
public APIs, without a network request. One proposed dependency is intentionally
spurious; the missing-antecedent interpretation receives disagreement. Resulting
precision and agreement describe this recorded regression fixture, not a live
model or authenticated human review. A second replay with a stale request digest
must be rejected.

`revision_before/paper.tex` and `revision_after/paper.tex` differ only in branch
A's locally scoped integer literal. The benchmark invokes the real offline paper
pipeline twice, compares current invalidation with independent labels, reads
completed pure-stage execution/reuse records, and rebuilds the store to check the
historical run. It does not run Lean or claim that a formal proof was reused.
Actual isolated verification and replay remain separate acceptance scenarios.

Reports include per-paper/category/family/split counts and equal-paper macro
scores alongside count-weighted micro scores. The long-input stress fixture is
flagged so its many remarks cannot conceal a failed small semantic case.
Unmeasured outcomes retain null values, explicit denominators and reasons.
Unresolved source intervals are merged before counting; PDF measurements use
reconstructed character intervals rather than invented byte offsets or boxes.
