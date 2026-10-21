"""Agent schedules (Phase 8f).

``GET/POST /orgs/{org}/agents/schedules``, ``PATCH/DELETE …/schedules/{id}``,
``GET …/schedules/{id}/runs``, ``POST …/schedules/{id}/run`` (run now).
The creator manages their own schedules; admins can see and pause any.
Flags ``buddies`` and ``scheduled_agents`` (501 when off).
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from rest_framework.exceptions import Throttled

from agents import cron
from brain.throttles import AISendThrottle
from agents.models import AgentRun, AgentSchedule
from agents.service import FLAG, queue_run
from buddies.services import is_admin, visible_buddies
from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit

MAX_PER_USER = 20


def _gate(request, view, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm("ai.use").has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not (
        effective_flag(org, membership, FLAG, default=False) and effective_flag(org, membership, "buddies", default=False)
    ):
        return org, Response({"error": "not_implemented", "details": "Scheduled agents are not enabled"}, status=501)
    return org, None


def _bad(details):
    return Response({"error": "invalid", "details": details}, status=400)


def _payload(s):
    return {
        "id": str(s.id),
        "name": s.name,
        "buddy": str(s.buddy_id),
        "created_by": str(s.created_by_id),
        "trigger_type": s.trigger_type,
        "cron": s.cron,
        "event": s.event,
        "instructions": s.instructions,
        "is_active": s.is_active,
        "paused_reason": s.paused_reason,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
    }


OUTPUT_MAX = 4000


def _run_payload(r, viewer=None):
    """A run. Its output (the buddy's answer) and proposals are shown to the creator only: the run
    read sources with the creator's access, which an admin reviewing the schedule may not have."""
    data = {
        "id": str(r.id),
        "status": r.status,
        "reason": r.reason,
        "error": r.error,
        "thread": r.chat_id,
        "proposals": r.proposals,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }
    if viewer is not None and r.schedule.created_by_id == viewer.id and r.chat_id:
        from actions.models import ActionProposal
        from brain.models import Message

        answer = (
            Message.objects.filter(chat_id=r.chat_id, role=Message.ROLE_ASSISTANT).order_by("-created_at", "-id").first()
        )
        data["output"] = answer.text[:OUTPUT_MAX] if answer else ""
        data["proposal_items"] = [
            {"id": str(p.id), "summary": p.summary, "status": p.status, "tool": p.tool_key}
            for p in ActionProposal.objects.filter(thread_id=r.chat_id, user=viewer).order_by("created_at")[:10]
        ]
    return data


def _apply_trigger(schedule, data, now):
    trigger = data.get("trigger_type", schedule.trigger_type)
    if trigger == AgentSchedule.TRIGGER_CRON:
        expr = data.get("cron", schedule.cron) or ""
        schedule.next_run_at = cron.validate(expr, now)  # raises CronError
        schedule.trigger_type, schedule.cron, schedule.event = trigger, expr, None
    elif trigger == AgentSchedule.TRIGGER_EVENT:
        event = data.get("event", schedule.event)
        if event not in AgentSchedule.EVENTS:
            raise cron.CronError(f"event must be one of {', '.join(AgentSchedule.EVENTS)}")
        schedule.trigger_type, schedule.event, schedule.cron, schedule.next_run_at = trigger, event, None, None
    else:
        raise cron.CronError("trigger_type must be cron or event")


class ScheduleListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Your agent schedules (admins see all)")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        qs = AgentSchedule.objects.filter(org=org)
        if not is_admin(request.user, org):
            qs = qs.filter(created_by=request.user)
        return Response([_payload(s) for s in qs.order_by("-created_at")[:200]])

    @extend_schema(summary="Create a schedule for a buddy you can use")
    def post(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        data = request.data or {}
        buddy = visible_buddies(request.user, org).filter(pk=data.get("buddy")).first() if data.get("buddy") else None
        if buddy is None:
            return Response({"error": "not_found", "details": "Buddy not found"}, status=404)
        instructions = str(data.get("instructions") or "").strip()
        if not instructions or len(instructions) > 4000:
            return _bad("instructions are required (at most 4000 characters)")
        if AgentSchedule.objects.filter(org=org, created_by=request.user).count() >= MAX_PER_USER:
            return _bad(f"at most {MAX_PER_USER} schedules per person")
        schedule = AgentSchedule(
            org=org, buddy=buddy, created_by=request.user, name=str(data.get("name") or "")[:80], instructions=instructions
        )
        try:
            _apply_trigger(schedule, data, timezone.now())
        except cron.CronError as exc:
            return _bad(str(exc))
        schedule.save()
        audit(request.user, "agent.schedule_create", target=schedule, payload={"trigger": schedule.trigger_type}, request=request, org=org)
        return Response(_payload(schedule), status=201)


def _schedule(request, org, schedule_id, write=False):
    schedule = AgentSchedule.objects.filter(org=org, pk=schedule_id).first()
    if schedule is None:
        return None
    if schedule.created_by_id == request.user.id:
        return schedule
    if is_admin(request.user, org) and (not write or set((request.data or {})) <= {"is_active"}):
        return schedule  # admins can read and pause, not rewrite another person's agent
    return None


class ScheduleDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Edit, pause or resume a schedule")
    def patch(self, request, org_id, schedule_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        schedule = _schedule(request, org, schedule_id, write=True)
        if schedule is None:
            return Response({"error": "not_found", "details": "Schedule not found"}, status=404)
        data = request.data or {}
        if "instructions" in data:
            text = str(data.get("instructions") or "").strip()
            if not text or len(text) > 4000:
                return _bad("instructions are required (at most 4000 characters)")
            schedule.instructions = text
        if "name" in data:
            schedule.name = str(data.get("name") or "")[:80]
        try:
            if {"trigger_type", "cron", "event"} & set(data):
                _apply_trigger(schedule, data, timezone.now())
            if "is_active" in data:
                schedule.is_active = bool(data["is_active"])
                schedule.paused_reason = "" if schedule.is_active else "paused_by_user"
                if schedule.is_active and schedule.trigger_type == AgentSchedule.TRIGGER_CRON:
                    schedule.next_run_at = cron.next_after(schedule.cron, timezone.now())
        except cron.CronError as exc:
            return _bad(str(exc))
        schedule.save()
        audit(request.user, "agent.schedule_update", target=schedule, payload={"fields": sorted(data)}, request=request, org=org)
        return Response(_payload(schedule))

    @extend_schema(summary="Delete a schedule")
    def delete(self, request, org_id, schedule_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        schedule = AgentSchedule.objects.filter(org=org, pk=schedule_id, created_by=request.user).first()
        if schedule is None:
            return Response({"error": "not_found", "details": "Schedule not found"}, status=404)
        audit(request.user, "agent.schedule_delete", target=schedule, request=request, org=org)
        schedule.delete()
        return Response(status=204)


class ScheduleRunListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Recent runs of a schedule")
    def get(self, request, org_id, schedule_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        schedule = _schedule(request, org, schedule_id)
        if schedule is None:
            return Response({"error": "not_found", "details": "Schedule not found"}, status=404)
        rows = AgentRun.objects.filter(schedule=schedule).select_related("schedule")[:50]
        return Response([_run_payload(r, request.user) for r in rows])


class ScheduleRunNowView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Run a schedule now (as its creator)")
    def post(self, request, org_id, schedule_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        schedule = AgentSchedule.objects.filter(org=org, pk=schedule_id, created_by=request.user).first()
        if schedule is None:
            return Response({"error": "not_found", "details": "Schedule not found"}, status=404)
        throttle = AISendThrottle()
        if not throttle.allow_request(request, self):
            raise Throttled(wait=throttle.wait())
        run = queue_run(schedule, "manual")
        if run is None:
            return Response({"error": "rate_limited", "details": "This schedule ran too often in the last hour"}, status=429)
        run.refresh_from_db()
        return Response(_run_payload(run, request.user), status=202)
