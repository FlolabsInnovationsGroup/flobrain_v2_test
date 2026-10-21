# Buddy evals and quality gates (market round M5)

Teams write test questions for a buddy, with what a good answer must (and must not) do, and run them
before they publish or change the buddy. A run goes through the buddy's real request pipeline in a
sandbox: nothing is executed, proposed, sent, notified or remembered. A gate can block a marketplace
submit, a new marketplace version or a buddy edit when the score falls under the pass mark or drops
too far below the last accepted version. Screen: `/w/{org}/buddies/evals`.

## Flags and permissions

| | |
|---|---|
| Flags | `buddies` and `buddy_evals` (each 501 `not_implemented` when off). The gate is a no-op while `buddy_evals` is off for the person. |
| `evals.manage` | Everything on the evals API (403 without it). Admins and owners have it by default; members do not. Also needed to override a gate block. |
| Buddy access | A buddy is reachable only if you may use it or you made it; `buddy.manage` reaches every buddy in the org (it can edit them anyway). Flo is never evaluated (it only routes). |

## Models (`evals`, migration `evals/0001_initial`)

- `EvalPolicy` (one per org): `judge_model` (empty: the org's Pulse routing decides; otherwise it must be on the platform allowlist), `max_run_tokens` (default 60,000), `max_run_cost` (default 1.00, empty for none), `concurrency` (1 to 8, default 3).
- `EvalSet`: buddy, name, `threshold` (pass mark, %), `max_drop` (points), `gate_marketplace`, `gate_saves`, `schedule` (`off`/`daily`/`weekly`), `baseline_run` (the last run the gate accepted).
- `EvalCase`: `input`, `context_doc_ids` (up to 5 documents the editor can open), `must_include[]`, `must_not_include[]`, `must_cite`, `expected_tool` (`""` = don't check, `"none"` = no action, or an action key), `forbidden_tools[]`, `max_words`, `language` (`ar`/`en`/`any`), `rubric` (empty = no AI judge).
- `EvalRun`: set, buddy, `fingerprint` (sha256 of base prompt, buddy prompt, tools, sources mode and model), `version_label` (`v1`, `v2`, ... per distinct fingerprint), `config` (the buddy settings tested, never returned whole), `status` (`queued`/`running`/`done`/`stopped`/`error`), `score`, `passed`, per-case `results` (expected, answer, captured tool calls, each check with its reason, judge verdict, sources, tokens, time), tokens, cost, duration, `triggered_by` (`manual`/`schedule`/`gate`).
- `EvalGateEvent`: buddy, context (`marketplace`/`save`), outcome (`passed`/`blocked`/`overridden`), per-set report, override reason, who, when.

## Endpoints (all under `/api/v2/orgs/{org}/evals`)

| | |
|---|---|
| `GET overview` | Buddies you can evaluate with set count and latest score; action keys; judge models |
| `GET\|POST sets` (`?buddy=`) | List or create a set |
| `GET\|PATCH\|DELETE sets/{set}` | Set with cases and score trend; edit pass mark and gate settings; delete |
| `POST sets/{set}/cases` | One case, or `{"cases": [...]}` (reviewed suggestions); at most 50 per set |
| `PATCH\|DELETE cases/{case}` | Edit or delete a case |
| `POST sets/{set}/suggest` | AI-drafted cases (not saved; validated like hand-written ones) |
| `GET\|POST sets/{set}/runs` | History, or run now (409 while a run of the set is going) |
| `GET runs/{run}` | Per-case expected vs got, with the previous version's per-case result |
| `POST gate-check` `{buddy, changes?}` | What the gate would say, optionally for unsaved prompt/tools/model/sources changes. Nothing is saved or accepted. |
| `GET gate-events?buddy=` | Gate history |
| `GET\|PUT settings` | Org eval policy |
| `GET documents?q=` | Documents you can open, for a case's sources |

Run, suggest and gate-check use the AI send throttle.

## How a run works

1. `runner.start` copies the buddy settings into the run, then queues `evals.run` (inline when jobs run eagerly, or when no worker exists; at most 50 cases).
2. `sandbox.prepare`: the same checks as `buddies.chat.run_buddy_turn` (provider configured, private-only policy), the same model choice (buddy default within the platform allowlist), and the same tools the buddy would be offered to the person running it (`actions.service.offered_tools` behind `ai_actions`, plus external agents).
3. For each case, `sandbox.turn` builds `BUDDY_BASE` + buddy instructions + the case documents as quoted `<source>` blocks, checks the org budget (`budget_decision`, including the downgrade model), calls `DirectProvider(org)` (Pulse routing applies) and records a `UsageEvent` with surface `eval`. Tool calls are captured as data and validated against the tool schema. No `ActionProposal`, `ExternalAgentCall`, chat `Message`, `BuddyAnswer`, notification or memory is written (tests assert the counts).
4. Deterministic checks (`evals.checks`): phrase matching ignores case, spacing and Arabic letter variants; citations are `[n]`; language is decided by counting Arabic and Latin letters.
5. The AI judge (`evals.judge`) gets the question, rubric, answer and action names inside tags as data and must answer exactly `{"score": 1-5, "reason": "..."}`. Anything else is an invalid verdict and fails the judge part. A judge score of 3 or more passes.
6. Case score: share of checks passed, with the judge counted as `(score - 1) / 4`. A case passes when every check passes and the judge (if any) gives 3+. Run score: mean case score in %. The run passes when it finished and the score is at least the pass mark.
7. Budget: a per-run cap on tokens and spend (`EvalPolicy`) on top of the org's AI budgets. When either is reached, the cases left are skipped and the run ends `stopped`.
8. Concurrency: up to `concurrency` cases at once on PostgreSQL outside a transaction; one by one otherwise.

Deliberate differences from a live turn, so runs are repeatable and nobody's private context reaches results other admins read: no workspace search (a case names its documents; only those the runner can open are used, and an answer built from a document the viewer can't open is hidden in the run view), and specialists don't get the runner's personal facts (`templates_extra.context_for`).

## The gate (`evals.gate`)

`check(buddy, user, context=..., override_reason=...) -> GateResult` runs every set of the buddy that guards the context, on the buddy as it is in memory (unsaved edits included). A set blocks when the score is under the pass mark, more than `max_drop` points under the previous version (the set's `baseline_run`, or else the newest finished run of other settings), or the run did not finish. A finished run of the same fingerprint from the last 7 days, newer than the last case edit, is reused. A pass or override makes those runs the new baseline. Each decision is an `EvalGateEvent` and an audit entry (`evals.gate.passed|blocked|overridden`, the override with its reason). An override needs `evals.manage` and a reason of 10+ characters, sent as `eval_override_reason` in the request body. A block is HTTP 409 `{"error": "eval_gate_failed", "details", "gate": {...}}`.

Wiring:
- Marketplace submit and new version: a marked hook in `marketplace/views.py` (`evals.gate.marketplace_block`), buddy listings only.
- Buddy edit: `evals.gate.buddy_save_block(request, org, buddy, fields)` is ready but not wired (`buddies/views.py` is outside this workstream). It only checks when prompt, tools, model or sources change. The lead adds it in `BuddyDetailView.patch`, after the `setattr` loop and before `buddy.save()`:

  ```python
  # --- M5 hook (evals): sets with "block saves" must still pass with the new settings.
  from evals.gate import buddy_save_block

  blocked = buddy_save_block(request, org, buddy, fields)
  if blocked is not None:
      return blocked
  # --- end M5 hook
  ```

## Suggest cases

The model gets the buddy's name, description, action keys, starter prompts and the counts of "not helpful" reason codes from the last 90 days. It never gets feedback notes, message text or the buddy's instructions. The draft cases are validated and returned; nothing is saved until a person keeps them.

## Scheduled runs

`manage.py run_scheduled_evals` (cron, hourly is fine) runs sets that are due daily or weekly, as the person who created the set, only while they are an active member with `evals.manage` and the flag on.

## Demo

`demo/extras/a5_evals.py` adds four demo documents (an NDA, a contractor agreement, a sign-ups report and a funnel), an eval set each for the Legal (8 cases), Data (7) and Sales (8) buddies, and five past runs per set. Sales run 4 tested a "more proactive" prompt for a new marketplace version: it scored 62.2% against 100% before, so the gate blocked it; run 5 is the fixed version. Results come from the real checks applied to scripted answers in `evals/demo_data.py`. `brain/llm/demo_handlers/evals.py` gives the same scripted answers for live "Run now" (the sandbox asks it first in demo mode, because the crew handler would otherwise answer buddy prompts), deterministic judge verdicts (`[flo:eval-judge]`) and suggestions (`[flo:eval-suggest]`). Every answer is labelled as demo output.

## Security notes

- Sandbox runs never create proposals or run tools; captured calls are shown as "would prepare" only.
- The buddy prompt is never returned by the evals API (runs keep it in `config` for reproducibility).
- Questions, rubrics and answers reach the judge as quoted data; tags in them are escaped.
- Every model call goes through the AI policy, the org budgets and usage accounting.

## Before production

Nothing beyond a configured `direct` provider. Optional: set a judge model in Settings and add `run_scheduled_evals` to cron (not added to the deploy files in this round).

## Known limits

- Evals use the platform key only (no BYOK) and don't run workspace search.
- One user turn per case (no multi-turn conversations).
- The gate runs synchronously in the submit request when no recent run can be reused, so a large set makes that request slow (at most 50 cases, bounded concurrency).
- Template listings (Content Studio) are not gated.
