# Phase 9 plan: Content Studio Buddy

Branch `v2/phase-7-ai` continues (local, not pushed). Flags `content_studio` and `social_publishing`, default off (501). Sources: `PLAN.md` Phase 9, spec 6.16 and 8.7, Decisions 35 to 37, Q15/Q16/Q18 defaults (E35: configurable, nothing hard-coded).

## Rules for every step

- **No public post without a human.** A publish job waits in `awaiting_approval`. Approving needs `content.publish` (not the uploader's own AI proposal). Any edit to render, copy, thumbnail, account or time changes `approval_hash` and resets approval. Consent is checked at approval **and** again right before publishing.
- **Consent (Decision 37).** Every person tagged on an asset needs a live `ConsentRecord` for the target scope. Revoking consent blocks pending publishes. Face detection may only count faces to block untagged ones; no identification or matching.
- **Workers are separate.** GPU workers on JarvisLabs authenticate with a hashed `WorkerToken`. They see only job specs, a presigned GET for the job's inputs and a presigned PUT for **that job's own output key**. They never get user tokens, social credentials or other jobs' files.
- **FFmpeg safety** lives in the worker, but the API never sends shell strings: the EDL is structured JSON validated against a schema; text for overlays travels as data.
- AI (clip suggestions, copy) goes through `direct` with strict JSON validation; cuts that fall mid-word are rejected. Never the legacy host.
- Storage is an interface: S3 presigned URLs when a bucket is configured, "Not configured" otherwise. No AWS change from this branch.

## 9a — Studio basics

Models `BrandKit`, `ContentTemplate` (FLOQ question card seeded per org on first use, editable), `MediaAsset`, `ContentProject`. Endpoints for brand kits, templates, assets (presign → complete), projects. Keys `content.view` (member), `content.edit` (member), `content.publish` (admin), `content.manage` (admin).

## 9b — Render workers

`workers.WorkerToken` (hash only, last4, revocable), `RenderJob`. Worker API under `/api/v2/workers/`: claim (SKIP LOCKED), heartbeat with progress, complete (validated output metadata, `gpu_seconds`), fail. Per-org monthly render quota and max source length are settings. GPU seconds feed budgets later (spec 6.19).

## 9c — Edit decisions and AI understanding

`EditDecisionList` versions (user or AI; undo = earlier version), transcript word timings on the asset, captions export SRT/VTT, `ClipSuggestion`. `POST …/suggest-clips` and `…/auto-edit` call `direct` and validate the JSON (ranges inside the media, on word boundaries).

## 9d — Consent, social accounts, publish

`ConsentRecord`, `SocialAccount` (credential = 7k encrypted key row), connector registry with a capabilities contract (no live connector until app credentials exist → "Not configured"), OAuth `state` (single-use, 10 min, PKCE) and callback, `PublishJob` with `approval_hash`, approve/cancel, publisher job that re-checks consent and approval hash.

## 9e — Templates, batches and copy

Template + rows → one render per row (bounded). Per-platform titles, descriptions and hashtags through `direct`. TTS stays an interface returning "Not configured" until Q18 is answered.

## Not in Phase 9

Live social connectors (need company developer apps, Q16), a GPU worker implementation (lives with the AI team, Q15), face detection model, TTS provider, metrics refresh against real platforms.
