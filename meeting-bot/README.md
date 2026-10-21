# FloBrain meeting assistant

Our own bot (no outside vendor). It joins Google Meet, Microsoft Teams or Zoom as a guest named **FloBrain assistant**, posts in the meeting chat that it records, records the meeting audio, and uploads it to FloBrain. FloBrain then transcribes it with our Whisper server and writes the summary, decisions and action items, the same way as calls made inside FloBrain.

## How a meeting goes

1. Someone with `meeting.manage` presses **Invite assistant** on a meeting in FloBrain, pastes the link, and confirms the host agrees to recording. FloBrain posts a recording notice in the room.
2. The bot claims the session (`POST /api/v2/workers/meeting-bots/claim`), opens the link, types its name and asks to join. The host admits it from the lobby (up to 10 minutes).
3. Once in, it posts its announcement in the chat, then starts recording what the meeting plays. It never sends audio or video of its own (fake, silent devices).
4. It leaves when the meeting ends, when it has been alone for 2 minutes, after `MEETING_BOT_MAX_MINUTES` (120), or when someone presses **Remove assistant** in FloBrain.
5. It uploads the recording (Ogg/Opus, mono 16 kHz) and FloBrain transcribes and summarizes it.

## Run it

```bash
# On the API host, once: a token that can only claim meeting-bot sessions
python manage.py worker_token --issue meeting-bot-1 --kind meeting_bot

docker build -t flobrain-meeting-bot meeting-bot
docker run -d --restart unless-stopped --shm-size=1g \
  -e FLOBRAIN_API_URL=https://api.example.com \
  -e FLOBRAIN_WORKER_TOKEN=fbw_... \
  flobrain-meeting-bot
```

On the API set `MEETING_BOT_VENDOR=self_hosted`. One container handles one meeting at a time; run more containers for more meetings at once. Each needs about 1 CPU and 1.5 GB of memory while in a call.

## Limits to know

- **The host must admit the bot** in Meet and Teams lobbies. Meet blocks guests in some Workspace orgs; then joining fails with `denied` or `timeout`.
- **Zoom:** the web client works only when the meeting allows guests without a Zoom sign-in. Otherwise it fails with `signin_required`. A Zoom Meeting SDK app would remove this limit, but that needs a Zoom developer app (we chose not to depend on outside accounts for now).
- **Selectors change.** Meet, Teams and Zoom change their pages. Each step tries several selectors; when a platform changes, update `src/platforms/<platform>.js`. Failures are reported to FloBrain with a short code (`no_join_button`, `denied`, `timeout`, `no_audio`).
- Check each platform's terms for your account before using a bot in customer meetings.

## Tests

```bash
npm test   # session logic with fake platforms; no browser needed
```
