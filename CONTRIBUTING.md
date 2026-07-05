# Contributing

## Merge policy — please read

These repositories are **private on the GitHub Free plan**, where branch protection and
rulesets are **not enforced**. GitHub will *not* stop a pull request with a failing check
from being merged, so this rule is on us, not the tooling:

> **Never merge a pull request while its CI check is red.**

Every PR runs the **`tests`** job (test suite + a coverage gate). Before you click
**Merge**:

1. Confirm **`tests`** is ✅ green on the PR.
2. Make sure the branch is **up to date with `main`** — merge/rebase the latest `main`
   in first. Testing against a stale `main` is what let cross-instance drift break UAT.
3. If the check is ❌ or still running, **wait or fix first**. A red merge is exactly how
   a broken change reaches UAT.

That is the whole convention. If we later move to GitHub Team/Enterprise, the same rule
becomes automatically enforced and this file just documents it.
