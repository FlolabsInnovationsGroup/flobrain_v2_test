# FloBrain Whisper service

Speech to text for FloBrain meetings, running on our own servers (no outside API). It speaks the OpenAI-style `POST /v1/audio/transcriptions` (multipart `file`, `response_format=verbose_json`), which is what the API calls with `ASR_BACKEND=http`.

```bash
docker build -t flobrain-whisper whisper-server
docker run -d -p 8000:8000 -v whisper-models:/home/whisper/.cache -e WHISPER_MODEL=small -e WHISPER_API_KEY=... flobrain-whisper
# API: ASR_BACKEND=http ASR_BASE_URL=http://whisper:8000
```

| Model | Where | Speed for 1 hour of audio (rough) |
|---|---|---|
| `small` (int8, CPU) | 4 vCPU | 15–25 minutes |
| `large-v3` (float16, GPU) | 1× T4 or better | 3–6 minutes |

Arabic is noticeably better with `large-v3`. The model downloads once on first start (about 0.5 GB for `small`, 3 GB for `large-v3`) into the mounted cache. `WHISPER_API_KEY` is required (the service refuses requests without one unless `WHISPER_ALLOW_NO_KEY=1` on a private test box); set the same value as `ASR_API_KEY` on the API. Up to 2 uploads are read at once (`MAX_CONCURRENT_UPLOADS`), streamed to disk. Audio is written to a temp file, transcribed and deleted; nothing is stored.

Tests: `python -m unittest test_app` (uses a fake model, no download).
