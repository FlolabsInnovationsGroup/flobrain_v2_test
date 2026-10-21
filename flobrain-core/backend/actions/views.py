"""Approved actions and team reports (Phases 8c, 8d).

Actions: ``GET /orgs/{org}/actions?status=``, ``POST …/actions/{id}/approve``
(optional edited ``arguments``), ``POST …/actions/{id}/reject``. Only the
person a proposal was made for decides it. Flag ``ai_actions`` (501 when off).

Reports: ``GET /orgs/{org}/teams/{team}/reports?kind=``, ``POST …/reports/generate``,
``POST …/reports/{id}/post``. Team lead or admin. Flag ``auto_reports``.
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from actions import reports as report_svc
from actions import service
from actions.models import ActionProposal, AutoReport
from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization, Team
from organizations.permissions import HasPerm, IsActiveOrgMember

STATUS_FOR = {"not_found": 404, "permission": 403, "expired": 409, "not_pending": 409, "invalid": 400, "not_available": 501}


def _gate(request, view, org_id, flag, perm="ai.use"):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm(perm).has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, flag, default=False):
        return org, Response({"error": "not_implemented", "details": f"{flag} is not enabled"}, status=501)
    return org, None


def _denied(exc):
    return Response({"error": exc.code, "details": str(exc)}, status=STATUS_FOR.get(exc.code, 403))


class ActionListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Your action proposals")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id, "ai_actions")
        if error:
            return error
        mine = ActionProposal.objects.filter(org=org, user=request.user)
        mine.filter(status=ActionProposal.STATUS_PROPOSED, expires_at__lte=timezone.now()).update(
            status=ActionProposal.STATUS_EXPIRED
        )
        qs = mine.order_by("-created_at")
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        return Response([service.payload(p) for p in qs[:100]])


class ActionDecisionView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Approve (runs it) or reject a proposal")
    def post(self, request, org_id, proposal_id, decision):
        if decision not in ("approve", "reject"):
            return Response({"error": "not_found", "details": "Unknown decision"}, status=404)
        org, error = _gate(request, self, org_id, "ai_actions")
        if error:
            return error
        try:
            if decision == "approve":
                edited = (request.data or {}).get("arguments")
                if edited is not None and not isinstance(edited, dict):
                    return Response({"error": "invalid", "details": "arguments must be an object"}, status=400)
                proposal = service.approve(proposal_id, request.user, org, edited)
            else:
                proposal = service.reject(proposal_id, request.user, org)
        except service.ActionDenied as exc:
            return _denied(exc)
        return Response(service.payload(proposal))


class ActionDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Edit a pending proposal's arguments (same validation as the proposal); it does not run")
    def patch(self, request, org_id, proposal_id):
        org, error = _gate(request, self, org_id, "ai_actions")
        if error:
            return error
        edited = (request.data or {}).get("arguments") if isinstance(request.data, dict) else None
        if not isinstance(edited, dict):
            return Response({"error": "invalid", "details": "arguments must be an object"}, status=400)
        try:
            proposal = service.edit(proposal_id, request.user, org, edited)
        except service.ActionDenied as exc:
            return _denied(exc)
        return Response(service.payload(proposal))


def _team_or_404(org, team_id):
    return get_object_or_404(Team, pk=team_id, org=org)


class TeamReportListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Reports for a team you lead")
    def get(self, request, org_id, team_id):
        org, error = _gate(request, self, org_id, report_svc.FLAG, perm="org.view")
        if error:
            return error
        try:
            team = report_svc.check_report_access(request.user, org, team_id)
        except service.ActionDenied as exc:
            return _denied(exc)
        qs = AutoReport.objects.filter(org=org, team=team)
        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return Response([report_svc.payload(r) for r in qs[:50]])


class TeamReportGenerateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Generate a daily standup or weekly report draft")
    def post(self, request, org_id, team_id):
        org, error = _gate(request, self, org_id, report_svc.FLAG, perm="org.view")
        if error:
            return error
        kind = (request.data or {}).get("kind")
        if kind not in (AutoReport.KIND_DAILY, AutoReport.KIND_WEEKLY):
            return Response({"error": "invalid", "details": "kind must be daily_standup or weekly_report"}, status=400)
        try:
            report = report_svc.generate_report(request.user, org, team_id, kind)
        except service.ActionDenied as exc:
            return _denied(exc)
        return Response(report_svc.payload(report), status=201)


class TeamReportPostView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Post a reviewed report to the team room")
    def post(self, request, org_id, team_id, report_id):
        from rooms.models import Room
        from rooms.services import post_message

        org, error = _gate(request, self, org_id, report_svc.FLAG, perm="org.view")
        if error:
            return error
        try:
            team = report_svc.check_report_access(request.user, org, team_id)
        except service.ActionDenied as exc:
            return _denied(exc)
        report = get_object_or_404(AutoReport, pk=report_id, org=org, team=team)
        if report.posted_at:
            return Response({"error": "already_posted", "details": "This report was posted"}, status=409)
        room = Room.objects.filter(org=org, team=team, kind=Room.KIND_TEAM).first()
        if room is None:
            return Response({"error": "not_found", "details": "The team has no room"}, status=404)
        message, reason = post_message(room, request.user, report.content[:8000])
        if reason:
            return Response({"error": "permission_denied", "details": reason}, status=403)
        report.posted_room, report.posted_at = room, timezone.now()
        report.save(update_fields=["posted_room", "posted_at"])
        from organizations.services.core import audit

        audit(request.user, "report.post", target=report, payload={"room": str(room.id)}, request=request, org=org)
        return Response(report_svc.payload(report))
