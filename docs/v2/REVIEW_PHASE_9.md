# Review: Phase 9 (Content Studio)

Date: 2026-10-20. Built by Claude in the container. Reviewed by a separate agent that had not seen the work being written (`git diff e97eb851..17cab5a6`), then fixed and re-tested. Branch `v2/phase-7-ai`, local only, not pushed.

## Findings and fixes

| # | Area | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | 9d consent | Consent was checked against the project's **current** sources, not what the render contains. Removing a source after rendering let footage of a person without consent be approved and published. Brand intro/outro/logos were never checked. | High | **Fixed**. `consent_problems(render)` checks every asset frozen in the render spec (sources and brand media, by id and key), at approval and at publish. |
| 2 | 9d consent | Anyone who could see an asset could replace its people tags (emptying the check), and duplicate tags padded the face count. | High | **Fixed**. Members can only add tags; removing a tag needs `consent.manage`. Tags are de-duplicated and the count uses distinct people. Every change is audited. |
| 3 | 9c | CPU DoS: word-boundary checks and caption mapping scanned the whole transcript per cut (38 s and 9 s for 65k words + 2000 cuts). | Medium | **Fixed**. Binary search over word starts and over kept ranges. Test: 60k words + 2000 cuts, both calls well under 10 s. |
| 4 | 9b | Cancelling a running render escaped the monthly quota. | Medium | **Fixed**. A cancelled job that a worker started still counts. |
| 5 | 9b/9d | Approval was tied to the output key, not the bytes; a worker could overwrite the file after validation; a source could be swapped after upload. | Medium | **Fixed**. The output ETag is recorded at completion, included in the approval hash, and compared again right before posting (`output_changed` → back to awaiting approval). Source ETags are recorded at `/complete`; a render is refused if a source changed. |
| 6 | 9d | Full-row saves in approve and edit could overwrite a concurrent cancel or a publish in progress. | Medium | **Fixed**. Approve is a conditional update from `awaiting_approval` and re-checks the hash; edit updates only changed fields and only if the status is unchanged. Test: cancel then approve → 409, stays cancelled. |
| 7 | 9a | `duration_seconds` was optional at upload completion, skipping the length cap. | Medium | **Fixed**. Required for video and audio. |
| 8 | 9 | Bad ids and dates caused 500s (publish job create, captions, revert, base version, consents, people, AI asset, calendar, worker bodies that are not objects). | Low | **Fixed**. All parse safely to 400/404. Test covers the list. |
| 9 | 9c | Auto-edit could cut any word-aligned range; user cuts with a `reason` were dropped; the transcript tag escape was case-sensitive. | Low | **Fixed**. Silence and noise cuts may contain no words; filler cuts only up to three known filler words and 2 s. Only earlier AI cuts (`by: ai`) are replaced. Case-insensitive escape. |
| 10 | 9d OAuth | A connect link sent to someone else could attach their channel to the sender's org; key rotation during the flow broke it. | Low | **Fixed**. The callback no longer connects anything: it parks the tokens and gives that browser a one-time code; the account is created only when the user who started the flow confirms the code while signed in (`POST …/social-accounts/confirm`). The key version is stored with the state. |
| 11 | 9 | The `content.publish` tool ignored the `content_studio` flag and accepted empty hashtags; inactive members could be tagged or given consent; malformed template variables broke batches. | Low | **Fixed**. Both flags; `minLength: 1`; active members only; template variables validated (simple names, string type, `maxLength` 1..5000, boolean `required`). |

## Checked and fine (reviewer)

- Every studio and publish query is org-scoped; member/manager/lead visibility holds.
- Brand kits and templates need `content.manage`.
- Storage keys are built by the server; presigned PUTs sign the content type.
- Workers: hashed tokens, constant-time compare, revocation, act only on held running jobs, receive only that job's input GETs and output PUT, validated completion.
- EDL operations are an allowlist with no filter strings; ranges bounded; no mid-word cuts.
- All AI through `DirectProvider` with budget and throttle; output validated; suggestions never auto-applied.
- Approval needs `content.approve` and the hash; edits reset it; consent at approval and publish; revocation blocks.
- OAuth state hashed, single-use, 10 minutes, platform-bound, PKCE; fixed redirect.
- Social tokens encrypted, never returned or logged; disconnect wipes them.
- The AI publish tool only submits.

## Proof

- SQLite and PostgreSQL 16: all Phase 0–9 tests pass (the one loader error is the unwired Phase 14 work in progress, not in this commit).
- `makemigrations --check`: no changes (`content_studio/0005_review_fixes`).
