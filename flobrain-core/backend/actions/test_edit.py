"""Edit before approving (spec 8.6): same validation, audited, the model's arguments kept."""

from datetime import timedelta

from django.utils import timezone

from actions.models import ActionProposal
from actions.tests import ActionBase
from organizations.models import AuditEvent
from rooms.models import RoomMessage
from tasks.models import Task


class EditBeforeApproveTests(ActionBase):
    def _propose(self, user, name, args):
        response, _, chat = self._turn(user, [(name, args)])
        proposals = response.json()["proposals"]
        self.assertEqual(len(proposals), 1, response.json())
        return proposals[0]["id"], chat

    def _decide(self, user, proposal_id, decision="approve", **body):
        self._auth(user)
        return self.client.post(f"{self.base}/actions/{proposal_id}/{decision}", body, format="json")

    def _edit(self, user, pid, arguments):
        self._auth(user)
        return self.client.patch(f"{self.base}/actions/{pid}", {"arguments": arguments}, format="json")

    def test_edit_saves_validates_and_audits_without_running(self):
        pid, _ = self._propose(self.member_a, "tasks__create", {"title": "Draft"})
        res = self._edit(self.member_a, pid, {"title": "Better title", "due_on": "2030-01-02"})
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["status"], "proposed")
        self.assertEqual(body["arguments"], {"title": "Better title", "due_on": "2030-01-02"})
        self.assertEqual(body["original_arguments"], {"title": "Draft"})
        self.assertTrue(body["edited"])
        self.assertIn("Better title", body["summary"])
        self.assertIn("title", body["schema"]["properties"])
        self.assertFalse(Task.objects.filter(title="Better title").exists(), "an edit never runs the tool")
        event = AuditEvent.objects.filter(org=self.org, action="action.edited").get()
        self.assertEqual(event.payload["fields"], ["due_on", "title"])
        # A second edit keeps the model's first version.
        self._edit(self.member_a, pid, {"title": "Third"})
        self.assertEqual(ActionProposal.objects.get(pk=pid).original_arguments, {"title": "Draft"})
        approved = self._decide(self.member_a, pid)
        self.assertEqual(approved.json()["status"], "executed")
        self.assertTrue(Task.objects.filter(title="Third").exists())
        executed = AuditEvent.objects.filter(org=self.org, action="action.executed").get()
        self.assertTrue(executed.payload["edited"])

    def test_edit_uses_the_same_validation(self):
        pid, _ = self._propose(self.member_a, "tasks__create", {"title": "Draft"})
        self.assertEqual(self._edit(self.member_a, pid, {"title": ""}).status_code, 400)
        self.assertEqual(self._edit(self.member_a, pid, {"title": "x", "extra": 1}).status_code, 400)
        self.assertEqual(self._edit(self.member_a, pid, {"title": "x", "due_on": "soon"}).status_code, 400)
        self.assertEqual(self._edit(self.member_a, pid, {"title": "x", "team": str(self.team_b.id)}).status_code, 404)
        self.assertEqual(self._edit(self.member_a, pid, "not an object").status_code, 400)
        self.assertEqual(ActionProposal.objects.get(pk=pid).arguments, {"title": "Draft"})
        self.assertFalse(AuditEvent.objects.filter(action="action.edited").exists())

    def test_edit_changes_a_room_post_body(self):
        pid, _ = self._propose(self.member_a, "rooms__post_message", {"room": str(self.room_a.id), "body": "Hello tem"})
        self._edit(self.member_a, pid, {"room": str(self.room_a.id), "body": "Hello team"})
        self.assertEqual(self._decide(self.member_a, pid).json()["status"], "executed")
        self.assertTrue(RoomMessage.objects.filter(room=self.room_a, body="Hello team").exists())
        self.assertFalse(RoomMessage.objects.filter(body="Hello tem").exists())

    def test_edit_on_approve_is_audited_with_fields(self):
        pid, _ = self._propose(self.member_a, "tasks__create", {"title": "Draft"})
        self._decide(self.member_a, pid, arguments={"title": "Edited on approve"})
        event = AuditEvent.objects.filter(org=self.org, action="action.edited").get()
        self.assertEqual(event.payload["fields"], ["title"])
        self.assertEqual(ActionProposal.objects.get(pk=pid).original_arguments, {"title": "Draft"})

    def test_unchanged_arguments_are_not_an_edit(self):
        pid, _ = self._propose(self.member_a, "tasks__create", {"title": "Same"})
        self.assertEqual(self._edit(self.member_a, pid, {"title": "Same"}).json()["edited"], False)
        self.assertFalse(AuditEvent.objects.filter(action="action.edited").exists())

    def test_only_the_proposer_edits_open_unexpired_proposals(self):
        pid, _ = self._propose(self.member_a, "tasks__create", {"title": "Mine"})
        self.assertEqual(self._edit(self.member_b, pid, {"title": "Hijack"}).status_code, 404)
        self.assertEqual(self._edit(self.owner, pid, {"title": "Hijack"}).status_code, 404)
        other = f"/api/v2/orgs/{self.other_org.id}/actions/{pid}"
        self._auth(self.member_a)
        self.assertEqual(self.client.patch(other, {"arguments": {"title": "x"}}, format="json").status_code, 403)
        self._decide(self.member_a, pid, "reject")
        self.assertEqual(self._edit(self.member_a, pid, {"title": "Late"}).status_code, 409)
        pid2, _ = self._propose(self.member_a, "tasks__create", {"title": "Old"})
        ActionProposal.objects.filter(pk=pid2).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self._edit(self.member_a, pid2, {"title": "New"}).status_code, 409)
        self.assertEqual(ActionProposal.objects.get(pk=pid2).status, "expired")
