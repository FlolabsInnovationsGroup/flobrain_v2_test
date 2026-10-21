"""Academy, industry packs and the AI-per-seat meter (growth round, W6).

Academy (flag ``academy``, every member, own progress only):
- ``GET  /orgs/{org}/academy``: lessons with my progress, and my badge
- ``GET  /orgs/{org}/academy/lessons/{key}``: one lesson (body in English and Arabic, check without answers)
- ``POST /orgs/{org}/academy/lessons/{key}/progress`` ``{step: read|tried}``
- ``POST /orgs/{org}/academy/lessons/{key}/check`` ``{answers: [int]}``
- ``POST /orgs/{org}/academy/coach`` ``{question, lesson?}``: the AI coach (``ai.use``; 30 questions a day)

Industry packs (flag ``packs`` and ``packs.install``):
- ``GET  /orgs/{org}/packs``; ``GET /orgs/{org}/packs/{key}/preview``
- ``POST /orgs/{org}/packs/{key}/install`` and ``…/uninstall`` with ``{confirm: true}``

AI included per seat (flag ``budgets``, ``ai.usage.view``): ``GET /orgs/{org}/ai-allowance``.
Sample allowance numbers until pricing is confirmed; see ``growth.allowance``.

A flag that is off answers 501 (like every V2 feature); a missing permission answers 403.
"""

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from growth import academy as A
from growth import allowance as AL
from growth import lessons as L
from growth import packs as P
from organizations.flags import effective_flag
from organizations.models import Organization, OrgMembership
from organizations.permissions import IsActiveOrgMember
from organizations.permissions.engine import can, is_org_owner_or_admin
from organizations.services.core import audit

COACH_PER_DAY = 30
MAX_QUESTION = 1000


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _bad(details):
    return Response({"error": "invalid", "details": details}, status=400)


def _gate(request, org_id, flag, label, perm=None):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, flag, default=False):
        return org, membership, Response({"error": "not_implemented", "details": f"{label} is not enabled"}, status=501)
    if perm and not can(request.user, perm, org):
        return org, membership, Response({"error": "permission_denied", "details": f"Missing permission: {perm}"}, status=403)
    return org, membership, None


# --- Academy ----------------------------------------------------------------------------------


class AcademyView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Academy lessons with my progress")
    def get(self, request, org_id):
        org, _, err = _gate(request, org_id, "academy", "The Academy")
        if err:
            return err
        progress = A.progress_rows(org, request.user)
        lessons = [A.lesson_summary(lesson, progress.get(lesson["key"])) for lesson in L.LESSONS]
        return Response(
            {
                "lessons": lessons,
                "done": sum(1 for row in lessons if row["progress"]["completed"]),
                "total": len(lessons),
                "badge": A.badge_payload(org, request.user),
            }
        )


class LessonView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="One Academy lesson (check answers are not included)")
    def get(self, request, org_id, key):
        org, _, err = _gate(request, org_id, "academy", "The Academy")
        if err:
            return err
        lesson = L.get(key)
        if lesson is None:
            return Response({"error": "not_found"}, status=404)
        return Response(A.lesson_detail(lesson, A.progress_rows(org, request.user).get(key)))


class LessonProgressView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Mark a lesson read, or its try-it step done")
    def post(self, request, org_id, key):
        org, _, err = _gate(request, org_id, "academy", "The Academy")
        if err:
            return err
        lesson = L.get(key)
        if lesson is None:
            return Response({"error": "not_found"}, status=404)
        step = _body(request).get("step")
        if step not in ("read", "tried"):
            return _bad("step must be read or tried")
        row = A.mark(org, request.user, key, step)
        return Response(A.progress_payload(row))


class LessonCheckView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Answer a lesson's check")
    def post(self, request, org_id, key):
        org, _, err = _gate(request, org_id, "academy", "The Academy")
        if err:
            return err
        lesson = L.get(key)
        if lesson is None:
            return Response({"error": "not_found"}, status=404)
        answers = _body(request).get("answers")
        if not isinstance(answers, list) or len(answers) != len(lesson["check"]):
            return _bad(f"answers must list one choice for each of the {len(lesson['check'])} questions")
        for answer, question in zip(answers, lesson["check"]):
            if not isinstance(answer, int) or isinstance(answer, bool) or not 0 <= answer < len(question["options"]):
                return _bad("each answer must be the number of one of the options")
        result = A.grade(org, request.user, lesson, answers)
        if result["badge_awarded"]:
            audit(request.user, "academy.badge", payload={"lessons": len(L.LESSONS)}, request=request, org=org)
            from notifications.services import notify

            notify(org, [request.user], "academy.badge", {"title": "You finished the FloBrain Academy"}, link="/academy")
        return Response(result)


class CoachView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Ask the Academy coach (answers from lesson text and your own workspace use)")
    def post(self, request, org_id):
        from brain.llm import direct
        from brain.llm.policy import check_ai
        from brain.llm.providers import DirectProvider
        from telemetry.models import UsageEvent
        from telemetry.pricing import (
            fill_missing_tokens,
            platform_budget_blocks,
            prompt_text,
        )
        from telemetry.writers import record_v2_provider_event

        org, membership, err = _gate(request, org_id, "academy", "The Academy", perm="ai.use")
        if err:
            return err
        data = _body(request)
        question = str(data.get("question") or "").strip()
        if not question:
            return _bad("question is required")
        if len(question) > MAX_QUESTION:
            return _bad(f"question is longer than {MAX_QUESTION} characters")
        lesson = None
        if data.get("lesson"):
            lesson = L.get(data.get("lesson"))
            if lesson is None:
                return _bad("lesson is not an Academy lesson")
        key = f"growth:coach:{org.pk}:{request.user.pk}:{timezone.now():%Y%m%d}"
        cache.add(key, 0, 60 * 60 * 26)
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, 60 * 60 * 26)
            count = 1
        if count > COACH_PER_DAY:
            return Response({"error": "rate_limited", "details": f"You can ask the coach {COACH_PER_DAY} questions a day"}, status=429)
        if not direct.is_configured():
            return Response({"error": "not_configured", "details": "No AI provider is configured"}, status=501)
        if platform_budget_blocks(org, request.user, UsageEvent.CREDENTIAL_PLATFORM):
            return Response({"error": "budget_exceeded", "details": "The org's monthly AI budget is used up"}, status=429)
        if check_ai(org, "direct"):
            return Response({"error": "private_only", "details": "Your org only allows self-hosted AI"}, status=409)
        context = A.coach_context(org, request.user, membership, current=lesson["key"] if lesson else None)
        messages = A.coach_messages(question, lesson, context)
        result = DirectProvider(org).complete(messages)
        result, estimated = fill_missing_tokens(result, prompt_text(messages), result.text or "")
        record_v2_provider_event(request.user, result, surface="learning", org=org, estimated=estimated, operation="chat")
        if not result.ok or not result.text:
            return Response({"error": result.error_code or "provider_error"}, status=502)
        return Response({"answer": result.text.strip()[:4000], "next_lesson": context["next"], "model": result.model})


# --- Industry packs ---------------------------------------------------------------------------


def _pack_or_404(key):
    return P.PACKS.get(str(key or ""))


class PackListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Industry packs and whether each is installed")
    def get(self, request, org_id):
        org, _, err = _gate(request, org_id, "packs", "Industry packs", perm="packs.install")
        if err:
            return err
        return Response({"results": [P.pack_summary(pack, P.active_install(org, pack["key"])) for pack in P.PACKS.values()]})


class PackPreviewView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Exactly what installing this pack would create, and what needs another feature")
    def get(self, request, org_id, key):
        org, _, err = _gate(request, org_id, "packs", "Industry packs", perm="packs.install")
        if err:
            return err
        pack = _pack_or_404(key)
        if pack is None:
            return Response({"error": "not_found"}, status=404)
        return Response(P.preview(org, request.user, pack))


class PackInstallView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Install a pack (idempotent; creates only what is missing)")
    def post(self, request, org_id, key):
        org, _, err = _gate(request, org_id, "packs", "Industry packs", perm="packs.install")
        if err:
            return err
        pack = _pack_or_404(key)
        if pack is None:
            return Response({"error": "not_found"}, status=404)
        if _body(request).get("confirm") is not True:
            return _bad("confirm must be true: open the preview first")
        record, created, skipped, first = P.install(org, request.user, pack)
        audit(
            request.user,
            "packs.install",
            target=record,
            payload={"pack": pack["key"], "created": [c["key"] for c in created], "skipped": skipped},
            request=request,
            org=org,
        )
        body = {"pack": P.pack_summary(pack, record), "created": created, "skipped": skipped}
        for row in body["created"]:
            row.pop("fingerprint", None)
        return Response(body, status=201 if first else 200)


class PackUninstallView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Uninstall a pack: removes only what nobody changed or used since")
    def post(self, request, org_id, key):
        org, _, err = _gate(request, org_id, "packs", "Industry packs", perm="packs.install")
        if err:
            return err
        pack = _pack_or_404(key)
        if pack is None:
            return Response({"error": "not_found"}, status=404)
        if _body(request).get("confirm") is not True:
            return _bad("confirm must be true")
        record = P.active_install(org, pack["key"])
        if record is None:
            return Response({"error": "conflict", "details": "This pack is not installed"}, status=409)
        result = P.uninstall(org, request.user, record)
        audit(
            request.user,
            "packs.uninstall",
            target=record,
            payload={"pack": pack["key"], "removed": [r["key"] for r in result["removed"]], "kept": result["kept"]},
            request=request,
            org=org,
        )
        return Response(result)


# --- AI included per seat ---------------------------------------------------------------------


class AllowanceView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="AI answers included per seat this month, use so far and the month-end projection (sample numbers)")
    def get(self, request, org_id):
        org, _, err = _gate(request, org_id, "budgets", "AI usage and budgets", perm="ai.usage.view")
        if err:
            return err
        return Response(AL.summary(org, request.user, admin=is_org_owner_or_admin(request.user, org)))
