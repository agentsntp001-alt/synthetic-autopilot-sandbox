# Public synthetic autopilot sandbox

A deliberately separate, public-only **technical demonstration**. It is not connected to any private repository, work files, document management, personal data, production environment, or regulated content. Only `sandbox/example.md` can be rewritten by an external model, and then only into a **draft pull request** for manual review. No automatic merges.

## State

**INACTIVE.** The workflow schedules a check every two hours at minute 17, but its execution job is skipped unless `SANDBOX_ENABLED=true`. Do not enable until repository protections, environment secrets, budget, independent review, and the exact fixture have been inspected and approved. The local unit tests use stubs and do not contact GitHub or Gemini.

## Create this separate repository

1. On GitHub create a **new, empty, public repository** named `synthetic-autopilot-sandbox`. Owner: the same account as your GitHub Free billing controls. Do **not** fork, clone, import, mirror, or publish the private business repository. Keep its privacy unchanged. Use `main` as default branch.
2. Upload only the six files in this package, retaining directories. These files contain no company names, project identifiers, real credentials, or private repository URLs. Do not upload local `.env`, keys, documents, QMS/GACP data, or the original PR diff.
3. Set up a **branch protection rule or active ruleset for `main`**: require a pull request, at least one independent approval, disallow force pushes and deletion, and require relevant status checks once CI exists. Avoid administrative bypass wherever GitHub's settings permit it. Verify rules apply after saving.
4. Under Settings → Environments create `synthetic-only`. Set Deployment branches/tags to **Selected branches and tags**, with `main` only; verify that non-`main` branches cannot access this environment. Leave the Gemini secret absent until protection has been checked. For unattended two-hour checks, an environment reviewer must not be required on every run; the main-branch review gate protects modifications to the workflow instead.
5. Confirm this account's **zero-dollar paid-usage budget** remains active. Under Settings → Actions → General enable **Allow GitHub Actions to create and approve pull requests**, leaving default workflow permissions read-only. The workflow uses narrowly declared job permissions. Confirm that your Google AI Studio API project is truly **unbilled / Free Tier**, and that `gemini-3.5-flash-lite` is available to that account. Do not add a billing method or switch to a paid tier.
6. Only after protections and independent source review: under the **`synthetic-only` environment secrets** add a secret named `GEMINI_API_KEY` using the key directly from Google AI Studio. Do not paste its value into the chat, git, a public issue, source file or an Actions log. Repository-wide Secrets are **not** the recommended location here; use Environment Secrets.
7. Under Settings → Secrets and variables → Actions → Variables, keep `SANDBOX_ENABLED` absent or `false` until the security review and an explicit activation decision. No workflow dispatch or Gemini call is authorized solely by creating this repository.
8. After written approval, set `SANDBOX_ENABLED=true` and use Actions → Synthetic Sandbox Autopilot → Run workflow on `main`. Verify one real Gemini call, `sandbox/example.md` as the only changed file, and one new **draft PR**. For PR-created CI, GitHub may require **Approve workflows to run**. Inspect status logs for accidental disclosures. Re-run once to confirm no duplicate API call or PR. Keep the original business repo's pilot PR unchanged and not activated.

## Safety design

- Immutable, source-reviewed goal, source path, and SHA-256 of the public fixture are embedded in `runner.py`. Any edit to that source requires a new review/update of the digest.
- The workflow exposes the Gemini secret and GitHub write token to the Python proposal step **only**. Third-party setup and artifact actions cannot read these variables from a job-wide environment.
- Environment secret access is restricted to `main`; the `execute` job checks both the default branch and `SANDBOX_ENABLED`. `permissions: {}` is the workflow-level default.
- The model receives only the vetted fictional text and hard-coded objective; not issue bodies, private repository content, metadata from other sources, or internal documents. The API key is in an HTTP header.
- The branch is created *before* calling Gemini. Failed, unmodified, or malformed model output therefore cannot trigger a repeated model call every two hours. Recovery after a file commit can create only a draft PR and cannot call Gemini again.
- The model cannot run arbitrary code. Its output is a size-limited Markdown replacement retaining the synthetic marker. Future changes still require an independent reviewer.
- Failure details and external API responses are not printed or included in artifacts; only controlled status categories. Action versions are pinned to verified commit SHAs.
- The token remains able to write repository contents, not a specific path. Thus repository isolation, branch rules, and independent reviews remain necessary. An owner with admin access can still potentially bypass controls; no arrangement eliminates all compromise risk.

## Limits and known open gates

The sample performs a single external inference for one pre-approved synthetic fixture. It **does not** process any issue from another repository, access private work material, or provide a general-purpose agent. The implementation is locally tested with mocks; no real external call or live GitHub-created PR is yet proven. A human security review of this new public repository, its rules, selected environment branches, free-tier billing status, and action logs is mandatory before activation. A public repository is searchable by others; never put proprietary information in it, including history, source comments, or issue text.

The model choice `gemini-3.5-flash-lite` is listed with a Free Tier in Google's published documentation as of 24 October 2026. Model availability and rates may change. There is no paid fallback in this code; the exact Google project/billing eligibility must still be checked in AI Studio. Free-tier prompts may be used for service improvement, which is acceptable here only because the data is entirely fictional and public.

## Offline test

From this repository root, run:

```sh
python -m unittest discover -s tests -v
```

The tests check paused-by-default, source checksum, one draft PR, branch reservation, no second model call, recovery without inference, invalid output, and credentials not needed for offline tests. They prove only mocked behavior.
