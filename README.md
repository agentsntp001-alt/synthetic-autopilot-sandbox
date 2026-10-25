# Public-only QUINN synthetic autopilot — work queue

**Status: code implemented in a Draft PR; intentionally NOT activated.** This repository is an isolated, public, fictional-data-only proof of an end-to-end task engine. It has **no access to any private company repository, production document, SharePoint, QMS, or GACP material**. No self-merges. Nothing here is an authorization to process real business data using a free AI tier.

## What the complete engine will do once independently reviewed and explicitly activated

```text
GitHub issues #2 / #3             Version-reviewed tasks/approved.json
         |                                      |
         +---- trusted owner / open issue -----+
                              |
                    Check allowed path, exact
                    objective and source SHA-256
                              |
                    Reserve a per-task branch
                    BEFORE external model call
                              |
                     Gemini 3.5 Flash-Lite
                  (fictional public fixture only)
                              |
                    Validate output and changes
                              |
                 Publish exactly ONE file change
                         as a DRAFT PR
                              |
                  HUMAN INDEPENDENT REVIEW
                          (no auto-merge)
```

### The work queue

`tasks/approved.json` is a code-reviewed list of tasks, **not a blind command copied from GitHub issue text**. Each row pins an issue number, unique immutable task identifier, allowed sandbox filepath, exact objective, and SHA-256 of the source file. An open trusted-author issue must exist. The issue body/comments are not sent to Gemini. Unapproved, edited, closed or anonymous issues cannot silently change objectives or files. Future tasks require a new reviewed PR into protected `main`.

Two real, fictional development tasks are staged:

- [#2](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/issues/2) – turn an invented draft into a practical public work handbook (`sandbox/handbook.md`)
- [#3](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/issues/3) – improve an accessible static dashboard containing exclusively fictional status information (`sandbox/dashboard.html`)

The queue processes at most **two distinct tasks per run** and **eight tasks per reviewed manifest**. Task branches use `auto/synthetic-<id>`. Creating a branch is a **single-use inference reservation**: if a model call fails, there is no automatic retry, even after a scheduled run or crash. An existing saved and valid result can be recovered to a Draft PR *without* repeating a model call. Existing PRs (open or closed) cannot be duplicated. No arbitrary files or executable output are accepted. HTML outputs use a strict static-element allowlist and prohibit active HTML, scripts, external resources, event handlers and embedded frames. Markdown outputs also forbid active HTML and external links. Outputs containing credential patterns or corporate identifiers are rejected. These rules reduce risk but cannot replace human review.

The controller's hard-coded `OWNER_REPO` prevents use against any other GitHub repository. `runner.py` remains as the earlier, single-task reference; **the scheduled workflow calls `autopilot_queue.py`**.

## Implementation / verification

- Fully offline unit and integration tests: `python -m unittest discover -s tests -v` (no real credentials, network or provider billings).
- Workflow: `.github/workflows/synthetic-sandbox.yml`. The `verify` job runs on **every PR** to satisfy the required `protect-main` status check, and has read-only contents access. On manual `workflow_dispatch`, the default `main` branch runs a **read-only preflight** of current issues and source checksums with no Gemini key; selecting a non-`main` branch runs the verification check only. `propose` is skipped unless all conditions hold: running on default `main`, `SANDBOX_ENABLED` explicitly `true`, and protected environment `synthetic-only` is accessible. Read-only CI and preflight jobs use pinned Actions. The write-capable `propose` job runs **no third-party Actions**: it clones the exact public `main` SHA without credentials and passes the Gemini secret explicitly only to the controller step. GitHub still makes its token accessible to the job via the `github.token` context; only independently reviewed code may run there. Task failures return a failing job status and a redacted log summary.
- `protect-main` is active on `main` with PR required, 1 approval, `verify` required, no bypass actors, no deletion and no force pushes: https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/rules/25836369 . These protections **do not constitute the independent approval** of this current PR.
- The model string is `gemini-3.5-flash-lite`, verified from Google's official model catalog. **The model's Free-Tier eligibility for the actual user project must be checked before activation.** Neither this repository nor the workflow adds a paid fallback. Google Free-Tier data handling varies by region and policy. Only public fictional data is allowed here, irrespective of tier.


## Operational preflight without Work, credentials, or live AI

After a separately authorized, independently reviewed merge, you can run **Actions → Synthetic Sandbox Autopilot → Run workflow → Branch: main** while `SANDBOX_ENABLED` is absent/false. Only the **preflight** job runs: it verifies GitHub issue ownership/state and source checksums using read-only permissions, and writes `sandbox-preflight.json` as a seven-day job artifact. It **never** contacts Gemini or creates branches/PRs. The result explicitly reports that environment protection and billing **remain unverified**; this check is **not** an activation approval.

If a future `GITHUB_TOKEN`-created Draft PR shows an *Approve workflows to run* banner, a human GitHub writer can approve its CI run. GitHub's documented behavior is to hold the `pull_request` workflow for that approval. As a fallback, the workflow also supports manual dispatch on the exact proposal branch to run the `verify` check without executing the AI job. No paid personal token or GitHub App is required for this workflow.

On a trusted development machine, `python3 autopilot_queue.py --dry-run` with `GITHUB_REPOSITORY`, `GITHUB_TOKEN`, and `GITHUB_REF=refs/heads/main` performs the same read-only check. **Do not** put tokens in commands, source files, issues, or screenshots. No GitHub admin secrets need to be shared with ChatGPT.

Task state `ATTENTION_REQUIRED` means one or more approved tasks failed safely and must be investigated; the workflow exits nonzero. A reserved but unchanged branch is an intentionally blocked **single-use model attempt** and will not be silently retried. It requires explicit manual disposition. No code currently deletes reservations or retries paid/free requests.

## Gates before activation (do not skip)

1. Independently review the exact latest PR commit and all changes, including code, workflow permissions and task manifest. All actual modifications to `main` must pass review; no reviewer may approve their own changes.
2. Confirm `synthetic-only` is a GitHub **Environment** whose **Deployment branches and tags** permit only `main`. Place the `GEMINI_API_KEY` **only in its environment secrets** after the environment restriction is verified. The public repository must never contain the key, and it must never appear in issue text, logs or a chat.
3. Confirm GitHub account's $0 hard budget blocks paid Actions usage. Independently verify that Google AI Studio project is **unbilled**, the model is available on the **free tier**, and no paid fallback or credit card is connected for this key. Never introduce new paid services or subscription trials.
4. Ensure repository Actions → General allows Actions to create pull requests. Keep default permissions read-only. Do not loosen `protect-main`, remove required checks, or set any bypass actor.
5. Only after independent review and explicit activation instruction: merge PR via the protected review process; then set repository variable `SANDBOX_ENABLED=true`, use Actions → Synthetic Sandbox Autopilot → Run workflow on `main`, and observe actual draft PRs for #2/#3. Ensure one file per PR and no secrets in output. A future check must not re-send the same task to Gemini.

### Pause immediately

Set `SANDBOX_ENABLED=false`, or disable the scheduled Actions workflow. The model does not run when the flag is absent or false. Open Draft PRs remain for human review.

## What this does NOT do

The present isolation does **not** make QUINN a fully autonomous Swiss Novatech employee. It cannot access private organizational tasks, files or protected internal documents, and no confidential data may ever cross to a free model through this public repository. A real corporate workflow would need a separately reviewed, private-data-safe architecture and explicit data-governance permission.

The initial PR is not merged; the code is not activated; no Gemini request has yet been made; the new Environment, billing/project eligibility and independent PR approval remain to be verified. This README is the source of truth for what the sample can and cannot do.
