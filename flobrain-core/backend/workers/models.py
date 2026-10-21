import hashlib
import secrets
import uuid

from django.db import models
from django.utils import timezone

PREFIX = "fbw_"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class WorkerToken(models.Model):
    """A GPU worker's credential (spec 8.7). Only the SHA-256 hash is stored; the raw token is shown once.

    Workers are platform-wide (one JarvisLabs pool serves every org). A token
    can only claim render jobs and touch the files of the job it holds.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80)
    KINDS = ("render", "meeting_bot")
    kind = models.CharField(max_length=12, default="render")  # a token works for one kind of job only
    token_hash = models.CharField(max_length=64, unique=True)
    last4 = models.CharField(max_length=4)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "worker_tokens"

    @classmethod
    def issue(cls, name: str, kind: str = "render"):
        if kind not in cls.KINDS:
            raise ValueError("unknown worker kind")
        raw = PREFIX + secrets.token_urlsafe(32)
        row = cls.objects.create(name=name[:80], kind=kind, token_hash=hash_token(raw), last4=raw[-4:])
        return row, raw

    def __str__(self):
        return f"WorkerToken {self.name} ****{self.last4}"
