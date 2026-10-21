from django.core.exceptions import ValidationError
from django.test import TestCase

from organizations.models import AuditEvent, Organization
from users.models import User


class AuditEventAppendOnlyTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Audit Org", slug="audit-org")
        self.user = User.objects.create(email="audit@example.com", password_hash="x")
        self.event = AuditEvent.objects.create(
            org=self.org,
            actor=self.user,
            action="test.create",
        )

    def test_update_refused(self):
        self.event.action = "test.update"
        with self.assertRaises(ValidationError):
            self.event.save()

    def test_delete_refused(self):
        with self.assertRaises(ValidationError):
            self.event.delete()
