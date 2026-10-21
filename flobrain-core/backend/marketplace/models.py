import uuid

from django.db import models
from django.utils import timezone


class Listing(models.Model):
    """A buddy or content template offered to the whole org (Phase 17e).

    ``snapshot`` is frozen at submission: approval approves exactly that
    content, and installs copy it. Editing the source later does not change
    an approved listing; the owner publishes a new version instead.

    Versions: every version is its own row sharing ``lineage`` (the id of
    version 1) with an increasing ``version``. A new version starts pending
    and needs the same ``marketplace.manage`` approval as the first one; when
    it is approved, the previously approved version becomes ``superseded``
    (still the source of copies already installed from it, no new installs).
    """

    KIND_BUDDY = "buddy"
    KIND_TEMPLATE = "content_template"
    KIND_CHOICES = [(KIND_BUDDY, "Buddy"), (KIND_TEMPLATE, "Content template")]
    PENDING, APPROVED, REJECTED, WITHDRAWN, SUPERSEDED = "pending", "approved", "rejected", "withdrawn", "superseded"
    STATUS_CHOICES = [(s, s) for s in (PENDING, APPROVED, REJECTED, WITHDRAWN, SUPERSEDED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="listings")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    source_id = models.UUIDField()
    title = models.CharField(max_length=80)
    description = models.CharField(max_length=500, blank=True, default="")
    snapshot = models.JSONField(default=dict)
    lineage = models.UUIDField(db_index=True)  # id of version 1; set in save()
    version = models.PositiveIntegerField(default=1)
    changelog = models.CharField(max_length=500, blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    submitted_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    decided_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(blank=True, null=True)
    decision_note = models.CharField(max_length=500, blank=True, default="")
    installs = models.PositiveIntegerField(default=0)
    # "Verified by FloBrain": set by platform staff only (growth round). Per version, like the snapshot it vouches for.
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    verified_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "marketplace_listings"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "kind", "source_id"], condition=models.Q(status="pending"), name="one_pending_listing_per_source"
            ),
            models.UniqueConstraint(fields=["lineage", "version"], name="one_listing_per_version"),
        ]

    def save(self, *args, **kwargs):
        if self.lineage is None:
            self.lineage = self.id
        super().save(*args, **kwargs)


class Install(models.Model):
    """A copy someone installed from a listing version, so they can be offered updates.

    Only the installer's own copy is linked; updating it never touches anyone else's.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="listing_installs")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="copies")  # the version installed
    lineage = models.UUIDField(db_index=True)
    version = models.PositiveIntegerField()
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=20, choices=Listing.KIND_CHOICES)
    target_id = models.UUIDField()  # the installer's Buddy or ContentTemplate
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "marketplace_installs"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["kind", "target_id"], name="one_install_per_copy")]


class Rating(models.Model):
    """One rating per person per listing (all versions share it through ``lineage``), only by people
    who installed it. ``version`` is the version they had when they last rated."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="listing_ratings")
    lineage = models.UUIDField(db_index=True)
    version = models.PositiveIntegerField(default=1)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    stars = models.PositiveSmallIntegerField()
    review = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "marketplace_ratings"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["lineage", "user"], name="one_rating_per_user_per_listing"),
            models.CheckConstraint(condition=models.Q(stars__gte=1, stars__lte=5), name="rating_stars_1_to_5"),
        ]
