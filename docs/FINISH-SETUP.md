# QUINN public synthetic sandbox — final one-time GitHub setup

**Only the fictional public sandbox** `agentsntp001-alt/synthetic-autopilot-sandbox`. The private company repository stays private and untouched. This package does not activate paid services, merge code or transmit documents.

## Code state / what's proven

- PR #1 contains the issue work queue and real read-only preflight. After merge, the same code runs from protected main. Tests validate behavior using mock APIs, **not** a live Gemini request.
- Rule `protect-main` (ID 25836369) protects `main` against deletion/force pushes and requires **zero approvals** plus the mandatory `verify` status check. On 2026-10-25 the owner explicitly chose to remove the second-account approval requirement for this **public synthetic-only sandbox**; this is NOT an independent security review. The change does not apply to the private corporate repository.
- The environment settings and account billing information cannot be verified by the connected GitHub read/write tools currently in use. Their status remains **UNKNOWN** until verified in your own Settings UI.
- No real model call, paid charge, or autonomous draft PR has been executed or claimed.

## Do these administrative settings together (iPhone browser or Work later)

1. Open [Sandbox repository → Settings → Environments](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/settings/environments). Create environment `synthetic-only` if absent. Under **Deployment branches and tags**, choose **Selected branches and tags**, add **Branch** name `main`, and save. Reopen the environment and confirm the restriction persisted. **Do not add any other allowed branch or tag.**
2. Open [Settings → Actions → General](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/settings/actions). Keep default workflow permissions **Read repository contents and packages permissions**, but enable **Allow GitHub Actions to create and approve pull requests**, then save. Do not enable automated merging.
3. In GitHub account Billing → Budgets, confirm the **$0.00 paid-usage Actions budget** and **Usage blocked**. Confirm no Actions excess spend is allowed. Do not upgrade or add a payment method.
4. In Google AI Studio, independently verify the key belongs to an **unbilled Free-Tier project**, the specific model `gemini-3.5-flash-lite` is currently allowed for that project, and there is **no paid fallback**. Do not add a payment method. Never share API key values in chats or GitHub files.
5. Only if Steps 1–4 are verified, use [Settings → Environments → synthetic-only](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/settings/environments) to add an **Environment Secret** named `GEMINI_API_KEY`, not a repository-wide secret. Keep the enabling Repository Variable `SANDBOX_ENABLED` **absent or `false`** at this stage.
6. Manually inspect the exact current PR commit and successful `verify` status on [PR #1](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/pull/1). There is no second reviewer; the owner accepts that limited assurance for the synthetic public sandbox only. Keep the mandatory PR, `verify` status, non-fast-forward prohibition, and deletion protection.

After Steps 1–6 and **explicit owner authorization**, merge PR #1 using the protected PR process. With `SANDBOX_ENABLED=false`, manually dispatch the workflow on `main` to run the read-only preflight and inspect its redacted results. Only if the results and costs meet the agreed limits may you subsequently enable `SANDBOX_ENABLED=true` and manually dispatch the first supervised fictional Gemini run. Confirm generated PRs are Draft and change only `sandbox/*.md` or `sandbox/*.html`. A future attempt must not call Gemini again for the same reservation.

## Never do

- Do not make the private business repository public, fork its content into this sandbox, or send internal data to Gemini Free.
- Do not enable external provider calls until the environment restriction, zero-paid-usage limits and a usable unbilled Gemini project are confirmed.
- Do not remove the `protect-main` pull-request requirement, mandatory `verify` status check, branch restrictions, or budget guard. The owner-approved zero-reviewer exception applies only to this synthetic sandbox.
- Do not silently delete a stuck reservation or introduce repeated external API calls.
