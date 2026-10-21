# Decisions needed from the owners (one sheet)

**Date:** 2026-10-21. **Use:** tick an answer, or write a different one, and send it back. Each line says what FloBrain does today, so nothing is blocked while you decide. Details are in `OPEN_QUESTIONS.md` (by Q number) and `TECH_DEBT.md` (by C number).

## Product and privacy

| # | Decision | What the code does now (default) | Options | Who |
|---|---|---|---|---|
| Q40 | Can owners and admins read DMs and group rooms they are not in? | No | Keep no / allow with an audit entry | product + legal |
| C8 | Can a support session (platform staff, with the owner's consent) read group rooms? | Yes, read-only and audited | Keep / block like DMs | product + legal |
| Q42 | Do platform admins keep access to every org without a support session? | Only through an audited, consented support session | Keep / remove entirely | leadership |
| Q41 | Can members use the org's AI key? | No: personal keys only; org keys for owners and admins | Keep / allow per team | product |
| Q4 | Who sees other people's time entries? | Team leads and admins; descriptions hidden when the person turns sharing off | Keep / leads hours only | product |
| Q20 | Default retention periods | None: nothing is deleted until an owner sets days | Set defaults per data type | legal + ops |
| C5 | Can team leads grant permissions to their own team? | No (owners and admins only) | Keep / allow for team-scoped keys | product |

## AI and content

| # | Decision | Default now | Options | Who |
|---|---|---|---|---|
| Q25 | Which self-hosted models count as "private only"? | None listed, so "private only" orgs get no AI | The JarvisLabs vLLM / Ollama model names | AI team |
| Q24 | Which outside AI agents (MCP) may orgs connect? | None (empty allowlist) | Notion, GitHub, Google Drive (read-only), after a skillspector scan | owner |
| Q18 | Text-to-speech provider for Arabic and English | None (voiceover says "not set up") | Pick one cloud provider | content team |
| Q16 | Social publishing apps | Sandbox only | YouTube and LinkedIn first, company-owned apps, private until audited | marketing + engineering |
| Q15 | Where is the AI video editor code? | Content Studio calls a worker API | Repo location | AI team |
| Q23 | Meeting bot in customer meetings: platform terms | Decided: our own bot; host consent and an announcement are required | Legal confirms Zoom, Meet and Teams terms | legal |

## Commercial

| # | Decision | Default now | Options | Who |
|---|---|---|---|---|
| Q22 | Prices | Plans exist with demo prices; entitlements not enforced | Per-seat price per plan, AI usage at cost, BYOK no markup | leadership |
| Q21 | First markets | Bootcamps and universities, MENA SMBs | Confirm | leadership |
| Q5 | Commission rate | Per project, set by `commissions.manage`; 35 % not hard-coded | Confirm | finance + ops |
| Q19 | Certificate wording and issuer | "FloLabs Innovations Group" | Confirm wording and branding | leadership |
| Q6 | Masterclass audience | The Notion team/people property; empty means everyone | Confirm | ops |

## Infrastructure (answers needed from AWS / DevOps)

Section 4 of `awssupport.md`: how migrations ran so far, the us-east-2 resources, staging in the same account or not, who owns the `flobrain.ai` DNS, CloudFormation diffs or manual edits, the budget for the RDS upgrade and staging.

## Language

| # | Decision | Default now | Who |
|---|---|---|---|
| C10 | Tone in Turkish, French and Portuguese | Turkish informal ("sen"), French "vous", Portuguese "você". Machine-quality first pass | A native speaker reviews each language |
