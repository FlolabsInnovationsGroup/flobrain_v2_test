"""Connectors declared in the catalog, waiting for the platform's OAuth apps (Phase 15).
They show as "not configured" until their env settings exist and their methods are written."""

from connectors.sdk import Connector, register

for key, name, description, kind, env in (
    ("google_calendar", "Google Calendar", "Meetings and task deadlines both ways.", "read", ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")),
    ("google_drive", "Google Drive", "Search and cite your Drive documents.", "read", ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")),
    ("gmail", "Gmail", "Draft and send emails through approved actions.", "write", ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")),
    ("zoom", "Zoom", "Meetings and cloud recordings into Recordings.", "read", ("ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET")),
    ("discord", "Discord bridge", "Mirror selected channels into rooms during the move.", "read", ("DISCORD_BOT_TOKEN",)),
):
    register(Connector(key=key, name=name, description=description, auth="oauth2", kind=kind, env=env))
