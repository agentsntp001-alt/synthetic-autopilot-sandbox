# QUINN public synthetic sandbox — final one-time GitHub setup

**Only the fictional public sandbox** `agentsntp001-alt/synthetic-autopilot-sandbox`. The private company repository stays private and untouched. This package does not activate paid services, merge code or transmit documents.

## Code state / what's proven

- A Draft PR contains the issue work queue and real-read-only preflight. Tests validate behavior using mock APIs, **not** a live Gemini request.
- Rule `protect-main` (ID 25836369) protects `main` against deletion/force pushes and requires **one independent approval** plus `verify` status check. This cannot be bypassed merely by passing tests.
- The environment settings and account billing information cannot be verified by the connected GitHub read/write tools currently in use. Their status remains **UNKNOWN** until verified in your own Settings UI.
- No real model call, paid charge, or autonomous draft PR has been executed or claimed.

## Do these administrative settings together (iPhone browser or Work later)

1. Open [Sandbox repository → Settings → Environments](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/settings/environments). Create environment `synthetic-only` if absent. Under **Deployment branches and tags**, choose **Selected branches and tags**, add **Branch** name `main`, and save. Reopen the environment and confirm the restriction persisted. **Do not add any other allowed branch or tag.**
2. Open [Settings → Actions → General](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/settings/actions). Keep default workflow permissions **Read repository contents and packages permissions**, but enable **Allow GitHub Actions to create and approve pull requests**, then save. Do not enable automated merging.
3. In GitHub account Billing → Budgets, confirm the **$0.00 paid-usage Actions budget** and **Usage blocked**. Confirm no Actions excess spend is allowed. Do not upgrade or add a payment method.
4. In Google AI Studio, independently verify the key belongs to an **unbilled Free-Tier project**, the specific model `gemini-3.5-flash-lite` is currently allowed for that project, and there is **no paid fallback**. Do not add a payment method. Never share API key values in chats or GitHub files.
5. Only if Steps 1–4 are verified, use [Settings → Environments → synthetic-only](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/settings/environments) to add an **Environment Secret** named `GEMINI_API_KEY`, not a repository-wide secret. Keep the enabling Repository Variable `SANDBOX_ENABLED` **absent or `false`** at this stage.
6. Request a **genuinely independent review of the exact current SHA** on [PR #1](https://github.com/agentsntp001-alt/synthetic-autopilot-sandbox/pull/1), from a GitHub collaborator/account that did not author the changes. Every new commit needs a fresh look at affected code. **Do not self-approve or weaken rules to merge.**

After Steps 1–6 and only after a **separate explicit activation decision**, merge PR #1 via protected GitHub review. With `SANDBOX_ENABLED=false`, manually dispatch the workflow on `main` to run the read-only preflight and inspect its redacted results. Only if the results and costs meet the agreed limits may you subsequently enable `SANDBOX_ENABLED=true` and manually dispatch the first supervised fictional Gemini run. Confirm generated PRs are Draft and change only `sandbox/*.md` or `sandbox/*.html`. A future attempt must not call Gemini again for the same reservation.

## Never do

- Do not make the private business repository public, fork its content into this sandbox, or send internal data to Gemini Free.
- Do not merge/activate merely because unit tests or this setup checklist say green.
- Do not remove the `protect-main` approval requirement, required status checks, branch restrictions, or budget guard.
- Do not silently delete a stuck reservation or introduce repeated external API calls.
