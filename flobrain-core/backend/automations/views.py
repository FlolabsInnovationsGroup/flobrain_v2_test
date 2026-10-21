"""Automations API (growth round W1). Flag ``automations`` (501 when off).

Viewing and running: ``automations.use``. Creating, changing, deleting, enabling, installing
templates and the settings: ``automations.manage``.

- ``GET/POST /orgs/{org}/automations``; ``GET/PATCH/DELETE /orgs/{org}/automations/{id}``
- ``POST …/automations/{id}/enable`` ``{enabled}``; ``POST …/automations/{id}/run`` (run now)
- ``GET …/automations/{id}/runs``; ``GET …/automations/runs``; ``GET …/automations/runs/{run}``
- ``POST …/automations/{id}/hook``: create or rotate the inbound webhook secret (shown once)
- ``GET …/automations/templates``; ``POST …/automations/templates/{key}/install``
- ``POST …/automations/draft`` ``{text}``: a proposed workflow from plain language (not saved)
- ``GET/PUT …/automations/settings``: hosts ``call_webhook`` may reach, and trusted hosts
- ``GET/PUT …/automations/me``: your opt-outs from the daily brief and nudges
- ``POST /hooks/automations/{id}``: public inbound webhook (HMAC-SHA256, rate limited)
"""

import hashlib
import hmac
import json
import secrets
import time

from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import Throttled
from rest_framework.response import Response

from automations import engine, templates
from automations.models import AutomationSettings, BriefOptOut, InboundHook, Workflow, WorkflowRun
from automations.schedule import describe, next_run
from automations.schema import WorkflowError, clean_hosts, clean_workflow
from brain.throttles import AISendThrottle
from core_v2.views import V2APIView, V2PublicAPIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember, can
from organizations.services.core import audit

MAX_WORKFLOWS = 50
HOOK_MAX_BYTES = 64 * 1024
HOOK_PER_MINUTE = 30
HOOK_SKEW_SECONDS = 300
HOOK_HEADER_SIGNATURE = "HTTP_X_FLOBRAIN_SIGNATURE"
HOOK_HEADER_TIMESTAMP = "HTTP_X_FLOBRAIN_TIMESTAMP"


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _bad(details):
    if isinstance(details, WorkflowError):
        return Response({"error": "invalid", "details": "; ".join(details.problems)[:2000], "problems": details.problems}, status=400)
    return Response({"error": "invalid", "details": str(details)}, status=400)


def _gate(request, view, org_id, perm="automations.use"):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm(perm).has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, engine.FLAG, default=False):
        return org, Response({"error": "not_implemented", "details": "Automations are not enabled"}, status=501)
    return org, None


def _name(user):
    from rooms.services import display_name

    return display_name(user) if user else None


def _settings_row(org):
    return AutomationSettings.objects.filter(org=org).first()


def _trigger_label(trigger):
    kind = trigger.get("type")
    if kind == "schedule":
        return describe(trigger)
    return {
        "manual": "only when run by hand",
        "room_message": f"when a room message says “{trigger.get('keyword', '')}”",
        "task_created": "when a task is created",
        "task_blocked": "when a task is blocked",
        "meeting_ended": "when a meeting ends",
        "customer_conversation": "when a customer conversation starts",
        "webhook": "when another system calls its webhook",
    }.get(kind, kind or "")


def _payload(workflow, viewer=None, manager=False):
    last = workflow.runs.order_by("-created_at").first()
    hook = InboundHook.objects.filter(workflow=workflow).first() if workflow.trigger_type == "webhook" else None
    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "description": workflow.description,
        "enabled": workflow.enabled,
        "trigger": workflow.trigger,
        "trigger_label": _trigger_label(workflow.trigger or {}),
        "steps": workflow.steps,
        "template_key": workflow.template_key,
        "created_by": str(workflow.created_by_id) if workflow.created_by_id else None,
        "run_as": {"id": str(workflow.run_as_id), "name": _name(workflow.run_as)} if workflow.run_as_id else None,
        "last_run_at": workflow.last_run_at.isoformat() if workflow.last_run_at else None,
        "next_run_at": workflow.next_run_at.isoformat() if workflow.next_run_at and workflow.enabled else None,
        "last_run": {"id": str(last.id), "status": last.status, "created_at": last.created_at.isoformat()} if last else None,
        "waiting_runs": workflow.runs.filter(status=WorkflowRun.WAITING).count(),
        "hook": (
            {
                "path": f"/api/v2/hooks/automations/{workflow.id}",
                "secret_hint": f"…{hook.last4}",
                "last_received_at": hook.last_received_at.isoformat() if hook.last_received_at else None,
            }
            if hook
            else None
        ),
        "can_manage": manager,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
    }


def _run_payload(run, viewer, manager, full=True):
    """Outputs carry data read with ``run_as``'s access: shown to that person and to managers only."""
    privileged = manager or run.workflow.run_as_id == viewer.id
    waiting = None
    log = []
    for entry in run.step_log or []:
        if not entry:
            continue
        item = dict(entry)
        if item.get("status") == "waiting":
            waiting = (item.get("detail") or {}).get("approval")
        if not privileged:
            item["output"] = None
            item["detail"] = {k: v for k, v in (item.get("detail") or {}).items() if k in ("approval", "error", "notified", "stopped")}
        log.append(item)
    data = {
        "id": str(run.id),
        "workflow": str(run.workflow_id),
        "workflow_name": run.workflow.name,
        "status": run.status,
        "reason": run.reason,
        "triggered_by": _name(run.triggered_by) if run.triggered_by_id else None,
        "error": run.error,
        "current_step": run.current_step,
        "steps_total": len(run.steps or []),
        "waiting_approval": waiting if run.status == WorkflowRun.WAITING else None,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    if full:
        data["step_log"] = log
        data["steps"] = run.steps
        data["trigger_payload"] = run.trigger_payload if privileged else {}
    return data


def _apply(workflow, org, user, data, partial):
    """Validate and copy fields onto ``workflow``. Raises WorkflowError."""
    if not partial or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name or len(name) > 120:
            raise WorkflowError(["name is required (at most 120 characters)"])
        workflow.name = name
    if "description" in data:
        workflow.description = str(data.get("description") or "")[:500]
    if not partial or "trigger" in data or "steps" in data:
        trigger, steps = clean_workflow(
            org,
            user,
            {"trigger": data.get("trigger", workflow.trigger), "steps": data.get("steps", workflow.steps)},
            _settings_row(org),
        )
        workflow.trigger, workflow.trigger_type, workflow.steps = trigger, trigger["type"], steps
        workflow.run_as = user
    if "enabled" in data:
        if not isinstance(data["enabled"], bool):
            raise WorkflowError(["enabled must be true or false"])
        workflow.enabled = data["enabled"]
    _schedule(workflow, org)


def _schedule(workflow, org):
    if workflow.trigger_type == "schedule" and workflow.enabled:
        workflow.next_run_at = next_run(workflow.trigger, org, timezone.now())
    else:
        workflow.next_run_at = None


class WorkflowListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Workflows in this organization")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        manager = can(request.user, "automations.manage", org)
        qs = Workflow.objects.filter(org=org).select_related("run_as")
        return Response([_payload(w, request.user, manager) for w in qs[:MAX_WORKFLOWS * 2]])

    @extend_schema(summary="Create a workflow (automations.manage)")
    def post(self, request, org_id):
        org, error = _gate(request, self, org_id, "automations.manage")
        if error:
            return error
        if Workflow.objects.filter(org=org).count() >= MAX_WORKFLOWS:
            return _bad(f"at most {MAX_WORKFLOWS} workflows per organization")
        workflow = Workflow(org=org, created_by=request.user, run_as=request.user)
        data = _body(request)
        try:
            _apply(workflow, org, request.user, data, partial=False)
        except WorkflowError as exc:
            return _bad(exc)
        workflow.template_key = str(data.get("template_key") or "")[:64] if data.get("template_key") in templates.BY_KEY else ""
        workflow.save()
        audit(request.user, "automation.create", target=workflow, payload={"trigger": workflow.trigger_type, "steps": len(workflow.steps), "enabled": workflow.enabled}, request=request, org=org)
        return Response(_payload(workflow, request.user, True), status=201)


def _workflow(org, workflow_id):
    return Workflow.objects.filter(org=org, pk=workflow_id).select_related("run_as").first()


def _missing():
    return Response({"error": "not_found", "details": "Workflow not found"}, status=404)


class WorkflowDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="One workflow")
    def get(self, request, org_id, workflow_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        workflow = _workflow(org, workflow_id)
        if workflow is None:
            return _missing()
        return Response(_payload(workflow, request.user, can(request.user, "automations.manage", org)))

    @extend_schema(summary="Change a workflow; you become the person it runs as (automations.manage)")
    def patch(self, request, org_id, workflow_id):
        org, error = _gate(request, self, org_id, "automations.manage")
        if error:
            return error
        workflow = _workflow(org, workflow_id)
        if workflow is None:
            return _missing()
        data = _body(request)
        try:
            _apply(workflow, org, request.user, data, partial=True)
        except WorkflowError as exc:
            return _bad(exc)
        workflow.save()
        audit(request.user, "automation.update", target=workflow, payload={"fields": sorted(k for k in data if k in ("name", "description", "trigger", "steps", "enabled"))}, request=request, org=org)
        return Response(_payload(workflow, request.user, True))

    @extend_schema(summary="Delete a workflow and its run history (automations.manage)")
    def delete(self, request, org_id, workflow_id):
        org, error = _gate(request, self, org_id, "automations.manage")
        if error:
            return error
        workflow = _workflow(org, workflow_id)
        if workflow is None:
            return _missing()
        audit(request.user, "automation.delete", target=workflow, payload={"name": workflow.name}, request=request, org=org)
        workflow.delete()
        return Response(status=204)


class WorkflowEnableView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Turn a workflow on or off (automations.manage)")
    def post(self, request, org_id, workflow_id):
        org, error = _gate(request, self, org_id, "automations.manage")
        if error:
            return error
        workflow = _workflow(org, workflow_id)
        if workflow is None:
            return _missing()
        enabled = _body(request).get("enabled", True)
        if not isinstance(enabled, bool):
            return _bad("enabled must be true or false")
        if enabled and (workflow.run_as is None or not engine.active_member(org, workflow.run_as)):
            # Nobody to run as: the person turning it on takes it over, with their own access.
            try:
                clean_workflow(org, request.user, {"trigger": workflow.trigger, "steps": workflow.steps}, _settings_row(org))
            except WorkflowError as exc:
                return _bad(exc)
            workflow.run_as = request.user
        workflow.enabled = enabled
        _schedule(workflow, org)
        workflow.save(update_fields=["enabled", "next_run_at", "run_as", "updated_at"])
        audit(request.user, "automation.enable" if enabled else "automation.disable", target=workflow, request=request, org=org)
        return Response(_payload(workflow, request.user, True))


class WorkflowRunNowView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Run a workflow now (automations.use; others' disabled workflows need automations.manage)")
    def post(self, request, org_id, workflow_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        workflow = _workflow(org, workflow_id)
        if workflow is None:
            return _missing()
        if not workflow.enabled and not can(request.user, "automations.manage", org):
            return Response({"error": "permission_denied", "details": "This workflow is turned off"}, status=403)
        if workflow.run_as is None:
            return _bad("nobody to run this workflow as; save it again first")
        throttle = AISendThrottle()
        if not throttle.allow_request(request, self):
            raise Throttled(wait=throttle.wait())
        run = engine.start_run(workflow, "manual", {"title": workflow.name}, triggered_by=request.user)
        audit(request.user, "automation.run", target=workflow, payload={"run": str(run.id)}, request=request, org=org)
        run.refresh_from_db()
        return Response(_run_payload(run, request.user, can(request.user, "automations.manage", org)), status=201)


class WorkflowRunsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Recent runs of one workflow")
    def get(self, request, org_id, workflow_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        workflow = _workflow(org, workflow_id)
        if workflow is None:
            return _missing()
        manager = can(request.user, "automations.manage", org)
        runs = workflow.runs.select_related("workflow", "triggered_by")[:50]
        return Response([_run_payload(r, request.user, manager, full=False) for r in runs])


class RunListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Recent runs of all workflows (?status=)")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        manager = can(request.user, "automations.manage", org)
        qs = WorkflowRun.objects.filter(org=org).select_related("workflow", "triggered_by")
        status = request.query_params.get("status")
        if status in dict(WorkflowRun.STATUS_CHOICES):
            qs = qs.filter(status=status)
        return Response([_run_payload(r, request.user, manager) for r in qs[:100]])


class RunDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="One run with its step log")
    def get(self, request, org_id, run_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        run = WorkflowRun.objects.filter(org=org, pk=run_id).select_related("workflow", "triggered_by").first()
        if run is None:
            return Response({"error": "not_found", "details": "Run not found"}, status=404)
        return Response(_run_payload(run, request.user, can(request.user, "automations.manage", org)))


class WorkflowHookView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Create or rotate the inbound webhook secret; it is shown once (automations.manage)")
    def post(self, request, org_id, workflow_id):
        from integrations import crypto

        org, error = _gate(request, self, org_id, "automations.manage")
        if error:
            return error
        workflow = _workflow(org, workflow_id)
        if workflow is None:
            return _missing()
        if workflow.trigger_type != "webhook":
            return _bad("this workflow is not started by a webhook")
        if not crypto.is_configured():
            return Response({"error": "not_configured", "details": "Encryption is not configured"}, status=501)
        secret = "whsec_" + secrets.token_urlsafe(32)
        hook = InboundHook.objects.filter(workflow=workflow).first() or InboundHook(org=org, workflow=workflow)
        hook.secret_ciphertext = crypto.encrypt(secret, hook.id, org.id)
        hook.key_version = crypto.current_key_version()
        hook.last4 = secret[-4:]
        hook.rotated_at = timezone.now()
        hook.save()
        audit(request.user, "automation.hook_rotate", target=workflow, request=request, org=org)
        return Response(
            {
                "path": f"/api/v2/hooks/automations/{workflow.id}",
                "secret": secret,
                "secret_hint": f"…{hook.last4}",
                "signature_header": "X-FloBrain-Signature: sha256=<hex of HMAC-SHA256(secret, timestamp + '.' + body)>",
                "timestamp_header": "X-FloBrain-Timestamp: <unix seconds>",
            },
            status=201,
        )


class TemplateListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Built-in workflow templates")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        installed = set(Workflow.objects.filter(org=org).exclude(template_key="").values_list("template_key", flat=True))
        return Response([{**templates.public(t), "installed": t["key"] in installed} for t in templates.TEMPLATES])


class TemplateInstallView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Install a template as a workflow (automations.manage)")
    def post(self, request, org_id, key):
        org, error = _gate(request, self, org_id, "automations.manage")
        if error:
            return error
        if key not in templates.BY_KEY:
            return Response({"error": "not_found", "details": "Template not found"}, status=404)
        if Workflow.objects.filter(org=org).count() >= MAX_WORKFLOWS:
            return _bad(f"at most {MAX_WORKFLOWS} workflows per organization")
        data = _body(request)
        try:
            built = templates.build(key, room=data.get("room"), emails=data.get("emails"))
        except templates.TemplateError as exc:
            return _bad(exc)
        if data.get("name"):
            built["name"] = str(data["name"])
        built["enabled"] = data.get("enabled", False)
        workflow = Workflow(org=org, created_by=request.user, run_as=request.user, template_key=key)
        try:
            _apply(workflow, org, request.user, built, partial=False)
        except WorkflowError as exc:
            return _bad(exc)
        workflow.save()
        audit(request.user, "automation.install", target=workflow, payload={"template": key, "enabled": workflow.enabled}, request=request, org=org)
        return Response(_payload(workflow, request.user, True), status=201)


class DraftView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    throttle_classes = V2APIView.throttle_classes + [AISendThrottle]

    @extend_schema(summary="Propose a workflow from plain language. Nothing is saved.")
    def post(self, request, org_id):
        from automations import ai

        org, error = _gate(request, self, org_id)
        if error:
            return error
        text = str(_body(request).get("text") or "").strip()
        if not text or len(text) > 2000:
            return _bad("describe the workflow in at most 2000 characters")
        try:
            raw = ai.draft(org, request.user, text)
        except ai.AIUnavailable as exc:
            return Response({"error": exc.code, "details": "The AI could not draft this workflow"}, status=exc.status)
        draft = {
            "name": str(raw.get("name") or "New workflow")[:120],
            "description": str(raw.get("description") or "")[:500],
            "trigger": raw.get("trigger") if isinstance(raw.get("trigger"), dict) else {"type": "manual"},
            "steps": [s for s in raw.get("steps") if isinstance(s, dict)][:20] if isinstance(raw.get("steps"), list) else [],
        }
        problems = []
        try:
            draft["trigger"], draft["steps"] = clean_workflow(org, request.user, draft, _settings_row(org))
        except WorkflowError as exc:
            problems = exc.problems
        audit(request.user, "automation.draft", payload={"valid": not problems, "steps": len(draft["steps"])}, request=request, org=org)
        return Response({"draft": draft, "valid": not problems, "problems": problems})


class SettingsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Hosts that workflows may call, and which skip the approval")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        row = _settings_row(org)
        return Response({"webhook_hosts": row.webhook_hosts if row else [], "trusted_hosts": row.trusted_hosts if row else []})

    @extend_schema(summary="Change the allowed and trusted hosts (automations.manage)")
    def put(self, request, org_id):
        org, error = _gate(request, self, org_id, "automations.manage")
        if error:
            return error
        data = _body(request)
        try:
            hosts = clean_hosts(data.get("webhook_hosts", []))
            trusted = clean_hosts(data.get("trusted_hosts", []))
        except WorkflowError as exc:
            return _bad(exc)
        if set(trusted) - set(hosts):
            return _bad("a trusted host must also be on the allowed list")
        row, _ = AutomationSettings.objects.update_or_create(
            org=org, defaults={"webhook_hosts": hosts, "trusted_hosts": trusted, "updated_by": request.user}
        )
        audit(request.user, "automation.settings", payload={"webhook_hosts": hosts, "trusted_hosts": trusted}, request=request, org=org)
        return Response({"webhook_hosts": row.webhook_hosts, "trusted_hosts": row.trusted_hosts})


class MyBriefView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _gate(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        membership = OrgMembership.objects.filter(org=org, user=request.user).first()
        if not effective_flag(org, membership, engine.FLAG, default=False):
            return org, Response({"error": "not_implemented", "details": "Automations are not enabled"}, status=501)
        return org, None

    def _state(self, org, user):
        off = set(BriefOptOut.objects.filter(org=org, user=user).values_list("kind", flat=True))
        return {"daily_brief": BriefOptOut.DAILY_BRIEF not in off, "nudges": BriefOptOut.NUDGES not in off}

    @extend_schema(summary="Whether you get the daily brief and overdue nudges")
    def get(self, request, org_id):
        org, error = self._gate(request, org_id)
        if error:
            return error
        from automations.briefs import brief_for

        return Response({**self._state(org, request.user), "preview": brief_for(org, request.user)})

    @extend_schema(summary="Opt in or out of the daily brief and nudges (any member)")
    def put(self, request, org_id):
        org, error = self._gate(request, org_id)
        if error:
            return error
        data = _body(request)
        for kind in BriefOptOut.KINDS:
            if kind not in data:
                continue
            if not isinstance(data[kind], bool):
                return _bad(f"{kind} must be true or false")
            if data[kind]:
                BriefOptOut.objects.filter(org=org, user=request.user, kind=kind).delete()
            else:
                BriefOptOut.objects.get_or_create(org=org, user=request.user, kind=kind)
        state = self._state(org, request.user)
        audit(request.user, "automation.brief_preferences", payload=state, request=request, org=org)
        return Response(state)


# --- inbound webhook ------------------------------------------------------------------


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def _flat(data) -> dict:
    out = {}
    for key, value in list(data.items())[:30]:
        if not isinstance(key, str) or len(key) > 40:
            continue
        if isinstance(value, (str, int, float, bool)):
            out[key.lower()] = str(value)[:1000]
    return out


class InboundHookView(V2PublicAPIView):
    """Start a webhook workflow. Unknown, disabled or switched-off workflows all answer 404."""

    @extend_schema(summary="Inbound webhook for a workflow (signed)")
    def post(self, request, workflow_id):
        from integrations import crypto

        bucket = f"automations:hook:{workflow_id}:{int(time.time() // 60)}"
        cache.add(bucket, 0, 120)
        try:
            count = cache.incr(bucket)
        except ValueError:
            count = 1
        if count > HOOK_PER_MINUTE:
            return Response({"error": "rate_limited", "details": "Too many calls"}, status=429)
        missing = Response({"error": "not_found"}, status=404)
        workflow = Workflow.objects.filter(pk=workflow_id, enabled=True, trigger_type="webhook").select_related("org").first()
        if workflow is None or not workflow.org.is_active or not engine.org_enabled(workflow.org):
            return missing
        hook = InboundHook.objects.filter(workflow=workflow).first()
        if hook is None:
            return missing
        body = request.body or b""
        if len(body) > HOOK_MAX_BYTES:
            return Response({"error": "too_large"}, status=413)
        timestamp = request.META.get(HOOK_HEADER_TIMESTAMP, "")
        signature = request.META.get(HOOK_HEADER_SIGNATURE, "")
        if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > HOOK_SKEW_SECONDS or not signature:
            return Response({"error": "invalid_signature"}, status=401)
        try:
            secret = crypto.decrypt(bytes(hook.secret_ciphertext), hook.id, workflow.org_id, hook.key_version)
        except crypto.CredentialCryptoError:
            return Response({"error": "not_configured"}, status=503)
        if not hmac.compare_digest(sign(secret, timestamp, body).encode(), signature.encode()):
            return Response({"error": "invalid_signature"}, status=401)
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response({"error": "invalid", "details": "body must be a JSON object"}, status=400)
        if not isinstance(data, dict):
            return Response({"error": "invalid", "details": "body must be a JSON object"}, status=400)
        key = hashlib.sha256(timestamp.encode() + b"." + body).hexdigest()[:40]
        with transaction.atomic():
            InboundHook.objects.filter(pk=hook.pk).update(last_received_at=timezone.now())
            run = engine.start_run(workflow, "webhook", _flat(data), event_key=f"webhook:{key}")
        if run is None:
            return Response({"status": "ignored"}, status=202)
        return Response({"status": "queued", "run": str(run.id)}, status=202)
