# Owner-side configuration checklist

Configure the public repository’s code owners and rules on the hosting platform.
The template contains no assigned owner. No server-side settings are implied.

1. Run and inspect CI on the implementation branch; do not trust YAML presence alone.
2. Require the stable `ci-required` check on the protected default branch.
3. Restrict force pushes and branch deletion, require resolved review conversations,
   and decide whether administrators may bypass rules.
4. Require review for trust/kernel/runner/workflow changes where another authorized
   reviewer is available. A solo maintainer must avoid a mandatory external-review
   rule that nobody can satisfy; document any deliberate bypass policy.
5. Confirm visibility and security-feature entitlement before enabling CodeQL,
   hosted SARIF, private-repo security services or attestations.
6. Confirm the manuscript validator's trusted base is bootstrapped before enabling
   paper CI as a required check. Review artifact visibility/retention for private papers.
7. Choose a repository license separately. This implementation did not select one
   or relicense existing work.
