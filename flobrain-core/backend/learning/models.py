import secrets
import uuid

from django.db import models
from django.utils import timezone


def _slug():
    return secrets.token_urlsafe(24)  # 192 bits, unguessable


class LearningPath(models.Model):
    """Ordered steps (documents, quizzes, links) for a team or role (Phase 11)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="learning_paths")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    steps = models.JSONField(default=list)  # [{kind: doc|quiz|link, ref, title}]
    team = models.ForeignKey("organizations.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "learning_paths"


class PathProgress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name="progress")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    done_steps = models.JSONField(default=list)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "learning_path_progress"
        constraints = [models.UniqueConstraint(fields=["path", "user"], name="unique_path_progress")]


class Quiz(models.Model):
    DRAFT, PUBLISHED = "draft", "published"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="quizzes")
    title = models.CharField(max_length=160)
    questions = models.JSONField(default=list)  # [{question, options: [..], answer: index}]
    pass_mark = models.PositiveSmallIntegerField(default=70)
    status = models.CharField(max_length=10, default=DRAFT)
    ai_drafted = models.BooleanField(default=False)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "learning_quizzes"


class QuizAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    answers = models.JSONField(default=list)
    score = models.PositiveSmallIntegerField(default=0)
    passed = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "learning_quiz_attempts"


class Certificate(models.Model):
    """Issued from real data and signed (Decision 40). The public page shows only ``data``."""

    KINDS = ("internship_completion", "path_completion")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="certificates")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="certificates")
    kind = models.CharField(max_length=24)
    data = models.JSONField(default=dict)
    signature = models.CharField(max_length=200)
    key_id = models.CharField(max_length=32)
    public_slug = models.CharField(max_length=64, unique=True, default=_slug)
    issued_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    issued_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "learning_certificates"


class PortfolioItem(models.Model):
    KINDS = ("project", "task", "certificate", "content")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="portfolio_items")
    kind = models.CharField(max_length=12)
    ref_id = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=1000, blank=True, default="")
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "portfolio_items"


class Mentorship(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="mentorships")
    mentor = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    mentee = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    starts_on = models.DateField(default=timezone.localdate)
    ends_on = models.DateField(null=True, blank=True)
    cadence = models.CharField(max_length=16, default="weekly")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "mentorships"


class MentorNote(models.Model):
    """Visible to the mentor and mentee only. Never exported (Phase 17e) and never shown to admins."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    mentorship = models.ForeignKey(Mentorship, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "mentor_notes"


class Cohort(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="cohorts")
    name = models.CharField(max_length=120)
    starts_on = models.DateField(default=timezone.localdate)
    members = models.ManyToManyField("users.User", related_name="cohorts", blank=True)
    instructors = models.ManyToManyField("users.User", related_name="instructed_cohorts", blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "cohorts"
