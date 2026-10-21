# Meetings stack

Everything FloBrain needs for meetings, on our own servers:

| Service | What it does | API settings |
|---|---|---|
| `livekit` | Voice and video calls inside FloBrain | `LIVEKIT_URL=wss://calls.example.com`, `LIVEKIT_API_URL=http://livekit:7880`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` |
| `egress` | Records calls (audio only) into the private bucket | (uses `egress.yaml`) |
| `whisper` | Speech to text | `ASR_BACKEND=http`, `ASR_BASE_URL=http://whisper:8000`, optional `ASR_API_KEY` |
| `meeting-bot` | Joins Zoom, Meet or Teams as "FloBrain assistant" | `MEETING_BOT_VENDOR=self_hosted` |

Then switch on `voice_video` (calls) and `meeting_bot` (assistant) for the org. Recording needs `meeting.manage`; it posts a notice in the room and shows a banner to everyone in the call. Recordings are transcribed, then summarized with the org's AI model (decisions and action items you can turn into tasks).

Network: LiveKit needs TCP 7880 behind TLS (wss), TCP 7881 and UDP 50000–50100 open to users. For people behind strict firewalls add TURN (LiveKit's built-in TURN on 443/TLS, see the LiveKit docs). Egress and the bot need outbound internet. See `docs/v2/awssupport.md` for the AWS version of this.
