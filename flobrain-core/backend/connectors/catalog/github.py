"""GitHub read connector: a fine-grained token with read access to one repository.
Open and recently closed issues and pull requests are copied as items that tasks can link to."""

import json
import re

from connectors.sdk import Connector, ConnectorError, register
from platform_api import net

REPO = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
API = "https://api.github.com"


def _get(path, token):
    try:
        status, body = net.fetch(
            "GET",
            API + path,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "FloBrain", "X-GitHub-Api-Version": "2022-11-28"},
            max_bytes=2 * 1024 * 1024,
        )
    except (net.UnsafeURL, OSError) as exc:
        raise ConnectorError("unreachable", "GitHub could not be reached") from exc
    if status in (401, 403):
        raise ConnectorError("invalid_credential", "GitHub refused the token")
    if status == 404:
        raise ConnectorError("not_found", "Repository not found, or the token can't read it")
    if status != 200:
        raise ConnectorError("provider_error", f"GitHub answered {status}")
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConnectorError("provider_error", "GitHub sent something unexpected") from exc


class GitHub(Connector):
    def validate(self, secret, config):
        repo = str((config or {}).get("repo") or "").strip()
        if not REPO.match(repo):
            raise ConnectorError("invalid", "repo must look like owner/name")
        if not secret or len(secret) > 300:
            raise ConnectorError("invalid", "a GitHub token is required")
        data = _get(f"/repos/{repo}", secret)
        return {"repo": data.get("full_name") or repo}

    def sync(self, connection, secret):
        repo = connection.config.get("repo", "")
        if not REPO.match(repo):
            raise ConnectorError("invalid", "bad repository")
        rows = _get(f"/repos/{repo}/issues?state=all&per_page=100&sort=updated", secret)
        items = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not isinstance(row.get("number"), int):
                continue
            url = str(row.get("html_url") or "")
            pull = row.get("pull_request") if isinstance(row.get("pull_request"), dict) else None
            items.append(
                {
                    "kind": "pull_request" if pull is not None else "issue",
                    "external_id": str(row["number"]),
                    "title": str(row.get("title") or "")[:300],
                    "url": url if url.startswith("https://github.com/") else "",
                    "state": "merged" if pull and pull.get("merged_at") else str(row.get("state") or "")[:24],
                }
            )
        return items

    def validate_offline(self, config):
        repo = str((config or {}).get("repo") or "").strip()
        if not REPO.match(repo):
            raise ConnectorError("invalid", "repo must look like owner/name")
        return {"repo": repo}

    def demo_items(self, connection):
        """Demo mode only: canned issues and pull requests, no network call."""
        repo = connection.config.get("repo", "")
        if not REPO.match(repo):
            return []
        rows = (
            (41, "Login times out on Android 14", "issue", "open"),
            (42, "Add crash reporting", "pull_request", "open"),
            (38, "Set up CI for the mobile app", "pull_request", "merged"),
            (44, "Dark mode for the settings screen", "issue", "open"),
        )
        return [
            {
                "kind": kind,
                "external_id": str(number),
                "title": title,
                "url": f"https://github.com/{repo}/{'pull' if kind == 'pull_request' else 'issues'}/{number}",
                "state": state,
            }
            for number, title, kind, state in rows
        ]


register(
    GitHub(
        key="github",
        name="GitHub",
        description="Link issues and pull requests to tasks and see their status on the task.",
        config_fields=[{"name": "repo", "label": "Repository", "hint": "owner/name"}],
        token_hint="A fine-grained token with read-only access to this repository. It is stored encrypted and never shown again.",
    )
)
