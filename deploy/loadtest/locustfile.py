"""Load test for the V2 API (Phase 16 external readiness). Run against staging, never production.

    pip install locust
    FLOBRAIN_EMAIL=... FLOBRAIN_PASSWORD=... FLOBRAIN_ORG=<org uuid> \
        locust -f deploy/loadtest/locustfile.py --host https://staging-api.example.com

Each simulated person signs in once and then does what people do most: open home, read tasks,
read rooms and messages, search, check notifications, start and stop the timer. No AI calls by
default (they cost money); set FLOBRAIN_ASK=1 to include one org question per person per minute.
Use a dedicated load-test org with seeded data. The credentials come from the environment only.
"""

import os
import random

from locust import HttpUser, between, task

ORG = os.environ.get("FLOBRAIN_ORG", "")
ASK = os.environ.get("FLOBRAIN_ASK") == "1"


class Member(HttpUser):
    wait_time = between(2, 8)

    def on_start(self):
        res = self.client.post(
            "/api/v2/auth/signin",
            json={"email": os.environ["FLOBRAIN_EMAIL"], "password": os.environ["FLOBRAIN_PASSWORD"]},
            name="signin",
        )
        res.raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {res.json()['access']}"
        rooms = self.client.get(f"/api/v2/orgs/{ORG}/rooms", name="rooms").json()
        self.rooms = [r["id"] for r in (rooms if isinstance(rooms, list) else rooms.get("results", []))][:20]

    def _org(self, path, name):
        return self.client.get(f"/api/v2/orgs/{ORG}{path}", name=name)

    @task(5)
    def home(self):
        self._org("/me/access", "me/access")
        self._org("/tasks", "tasks")

    @task(4)
    def read_room(self):
        if self.rooms:
            self._org(f"/rooms/{random.choice(self.rooms)}/messages", "room messages")

    @task(2)
    def notifications(self):
        self._org("/notifications", "notifications")

    @task(2)
    def search(self):
        self._org("/search?q=" + random.choice(["launch", "design", "bug", "report"]), "search")

    @task(1)
    def timer(self):
        self.client.post(f"/api/v2/orgs/{ORG}/timer/start", json={}, name="timer start")
        self.client.post(f"/api/v2/orgs/{ORG}/timer/stop", json={}, name="timer stop")

    @task(1)
    def ask(self):
        if ASK:
            self.client.post(f"/api/v2/orgs/{ORG}/knowledge/ask", json={"question": "What did we decide this week?"}, name="ask")
