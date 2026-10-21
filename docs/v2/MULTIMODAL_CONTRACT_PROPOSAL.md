# Multimodal contract proposal

Proposal only. This repo does not change `FlolabsInnovationsGroup/multi-modal-perception`.

Read from `main` at `1d875b8` on 2026-10-20. The EC2 host that production calls (`http://35.153.90.219:8000`) may not be that commit. Confirm against the running process before changing it.

## What the service does today

- `POST /process` and `POST /openAI` run the same logic. `GET /health` is the health check.
- Multipart form. The only inputs are `text_input` (optional string) and `audio_file` (optional file). There is no `model`, image, document, `messages[]`, or credential field. Extra fields, including `model`, are ignored.
- Each call is one user message plus a fixed system prompt ("fast, concise multimodal perception assistant ... short, actionable analysis"). The service does not receive conversation history unless the caller stuffed it into `text_input`.
- Model is `OPENAI_MODEL`, default `gpt-4o-mini`, `max_tokens=256`, `temperature=0.4`. Audio is transcribed with `gpt-4o-mini-transcribe` and then answered. The transcript is not returned.
- Response JSON is `result`, `model`, and `file_type`. `total_tokens` is computed and not returned.
- `422` when both inputs are empty. `500` with a text `detail` when the service is misconfigured or crashes. When the OpenAI call itself fails: HTTP 200 and `Perception system temporarily unavailable. Echoing input: <the user's text>`. No error codes.
- No auth. `MULTIMODAL_API_KEY` is never checked. No credential validation, embeddings, or transcription endpoint. One platform OpenAI key. BYOK is not supported.
- An in-memory cache is keyed by the lowercased message. It is shared by every user, it never expires, and it has no size limit. The same text returns the same cached answer for everyone, and the process grows until restart.

## What V1 Django sends

`brain/views.py` builds a list: a system line `You are FloBrain, a helpful AI assistant.`, then every user and assistant text in that chat, oldest first. `brain/llm/multimodal_adapter.py` flattens that list into one `text_input` string (`System:`, `User:`, `Assistant:`, blank line between parts) and POSTs it to `/process`. Images on the user message are not sent. Audio is not sent. A client `model` value is sent as an extra form field, which this service ignores. If `MULTIMODAL_API_KEY` is set, Django adds `Authorization: Bearer`; the service does not read it. Django reads `total_tokens` from the JSON and stores `0` when the field is missing, which is every successful call today.

## What we are asking for

1. Check an API key. Reject missing or wrong keys with 401. Do not accept anonymous calls from the internet.
2. Serve the API over HTTPS.
3. Return real HTTP error codes when the OpenAI call fails. Do not return HTTP 200 with an "Echoing input" body.
4. Include token counts in the success JSON: `prompt_tokens`, `completion_tokens`, and `total_tokens`.
5. Accept an optional `model` field, and use it only when it is on an allowlist you publish.
6. Accept structured `messages[]` so history is not pasted into a single user string.
7. Add a transcript-only endpoint that returns the transcript and does not also answer it.
8. Remove the shared unbounded cache, or replace it with a bounded per-user cache that expires. A cache key must not be the raw message text shared across users.

Until those exist, FloBrain V2 keeps `multimodal_legacy` as a thin wrap of today's call, and does not send org documents, memory, files, or credentials through it.
