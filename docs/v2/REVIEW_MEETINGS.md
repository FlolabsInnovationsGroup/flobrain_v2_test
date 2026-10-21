# Review: meetings inside FloBrain and our own meeting assistant

An independent agent reviewed `278b8290..c0905513` and confirmed seven findings with throwaway tests. It found nothing that lets one org reach another org's data. Every finding is fixed; tests added where marked.

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | Two "start recording" clicks could start two recordings; stop only stopped one while the banner said stopped | The start is claimed with a conditional update first; a second start gets 409; a failed start releases the claim (test) |
| 2 | Medium | Transcriptions could stay "queued" or "running" for good (no worker, or an unexpected error) | No worker: the recording is marked failed and the API answers 501; any error marks it failed; a job stuck for 90 minutes can be started again (tests) |
| 3 | Medium | A bot waiting in the lobby was marked lost after 3 minutes, then recorded anyway, and its audio was accepted | The bot reports every 15 seconds while it waits; lobby sessions get 15 minutes; audio is refused from failed sessions and from sessions that never joined (tests) |
| 4 | Medium | "Remove assistant" was ignored while the bot waited in the lobby | The bot checks every reply, including in the lobby and right before recording, and leaves without recording (bot test) |
| 5 | Medium | The bot recorded even when its announcement didn't go out | The announcement must show up in the meeting chat; otherwise it leaves with `announce_failed` (bot test) |
| 6 | Medium | Chromium's fake microphone and camera send a beep and a test pattern | The fake devices play a silent file and a black frame built into the image; Zoom also mutes and stops video |
| 7 | Medium | The recorder could hang if ffmpeg exited early, or crash the process if ffmpeg was missing | `stop()` always resolves, errors are caught, stderr is bounded (bot test) |
| 8 | Medium | Days-old bot requests were still claimed (a reused link could mean a different meeting) | Requests expire after 30 minutes (test) |
| 9 | Medium | After "End for everyone", a 2-hour token could recreate the room | Rooms are created only by FloBrain (`auto_create: false`), tokens last 10 minutes (test) |
| 10 | Medium–low | "Stop recording" stuck on when the recording had already died | LiveKit's not-found counts as stopped (test) |
| 11 | Medium–low | Large uploads used about 10× their size in memory on the Whisper service and the worker | The Whisper service streams the body to disk and parses it in place, at most 2 uploads at once, and requires its key; the worker streams audio to disk and to Whisper (tests) |
| 12 | Low | Team-scoped managers could record but not transcribe or summarize, and the page hid their controls | Same team-scoped check everywhere; the page shows controls per meeting (`can_manage`) |
| 13 | Low | Webhook keys could carry `../` after our prefix; a non-object `egressInfo` gave 500; tokens without expiry were accepted | Strict key pattern, type checks, `exp` required (test) |
| Minor | Low | Speech could close the transcript block in the summary prompt | `<transcript` is escaped like `<source` |

Left as TECH_DEBT: removing someone from a call when they lose room access mid-call (`RemoveParticipant`), and per-speaker labels.
