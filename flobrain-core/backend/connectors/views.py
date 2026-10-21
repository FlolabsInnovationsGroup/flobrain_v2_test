"""Integrations (Phase 15): catalog, connect, sync, disconnect, task links.

``integrations.manage`` (admins) connects and disconnects. Imported items are visible only to
people who can open the connection's room. Disconnecting wipes the secret, marks the connection
revoked and stops all sync jobs (a running sync re-checks before writing).
"""

import uuid

from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

import connectors.catalog  # noqa: F401  (registers the catalog)
from connectors import sdk
from connectors.jobs import JOB, is_demo
from connectors.models import Connection, ExternalItem, TaskLink
from core_v2.views import V2APIView
from integrations import crypto
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import IsActiveOrgMember
from organizations.permissions.engine import can
from organizations.services.core import audit
from rooms.services import accessible_rooms

FLAG = "integrations"


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _gate(request, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, FLAG, default=False):
        return org, Response({"error": "not_implemented", "details": "Integrations are not enabled"}, status=501)
    return org, None


def _manager(request, org):
    return can(request.user, "integrations.manage", org)


def _connection_payload(c):
    return {
        "id": str(c.id),
        "connector": c.connector,
        "label": c.label,
        "room": str(c.room_id),
        "room_name": c.room.name,
        "config": c.config,
        "status": c.status,
        "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
        "last_error": c.last_error,
        "items": c.items.count(),
        "demo": is_demo(c),
    }


class CatalogView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Available connectors and this org's connections")
    def get(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        rooms = accessible_rooms(request.user, org)
        conns = Connection.objects.filter(org=org).select_related("room")
        if not _manager(request, org):
            conns = conns.filter(room__in=rooms, status=Connection.ACTIVE)
        visible = set(rooms.values_list("id", flat=True)) if hasattr(rooms, "values_list") else {r.id for r in rooms}
        rows = []
        for c in conns.order_by("-created_at"):
            row = _connection_payload(c)
            if c.room_id not in visible:
                row["room_name"] = ""  # managers see it exists, not private room names
                row["room_hidden"] = True
            rows.append(row)
        return Response({"connectors": [c.describe() for c in sdk.catalog()], "connections": rows})


class ConnectView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Connect an integration to a room (integrations.manage)")
    def post(self, request, org_id, key):
        org, err = _gate(request, org_id)
        if err:
            return err
        if not _manager(request, org):
            return Response({"error": "permission_denied", "details": "Missing permission: integrations.manage"}, status=403)
        connector = sdk.get(key)
        if connector is None:
            return Response({"error": "not_found"}, status=404)
        if not connector.describe()["available"]:
            return Response({"error": "not_configured", "details": f"{connector.name} is not set up on this server yet"}, status=501)
        demo = bool(getattr(settings, "DEMO_MODE", False))
        if not demo and not crypto.is_configured():
            return Response({"error": "not_configured", "details": "Encryption is not configured"}, status=501)
        data = _body(request)
        room = accessible_rooms(request.user, org).filter(pk=_uuid(data.get("room"))).first()
        if room is None:
            return Response({"error": "invalid", "details": "Choose a room you can open; items will be visible to its members"}, status=400)
        secret = str(data.get("token") or "")
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        if demo:
            return self._demo_connect(request, org, key, connector, room, data, config)
        try:
            clean = connector.validate(secret, config)
        except sdk.ConnectorError as exc:
            return Response({"error": exc.code, "details": exc.details}, status=400)
        conn = Connection(org=org, connector=key, label=str(data.get("label") or connector.name)[:120], room=room, config=clean, created_by=request.user)
        conn.secret_ciphertext = crypto.encrypt(secret, conn.id, org.id)
        conn.key_version = crypto.current_key_version()
        conn.save()
        audit(request.user, "integration.connect", target=conn, payload={"connector": key, "room": str(room.id)}, request=request, org=org)
        from jobs.queue import enqueue

        enqueue(JOB, {"connection_id": str(conn.id)})
        conn.refresh_from_db()
        return Response(_connection_payload(conn), status=201)

    def _demo_connect(self, request, org, key, connector, room, data, config):
        """Demo mode: check the config offline, store no token, and sync canned items. No network."""
        from jobs.queue import enqueue

        try:
            clean = connector.validate_offline(config)
        except sdk.ConnectorError as exc:
            return Response({"error": exc.code, "details": exc.details}, status=400)
        label = str(data.get("label") or connector.name)[:110]
        conn = Connection.objects.create(
            org=org, connector=key, label=f"{label} (demo)", room=room, config={**clean, "demo": True}, created_by=request.user
        )
        audit(request.user, "integration.connect", target=conn, payload={"connector": key, "room": str(room.id), "demo": True}, request=request, org=org)
        enqueue(JOB, {"connection_id": str(conn.id)})
        conn.refresh_from_db()
        return Response(_connection_payload(conn), status=201)


class ConnectionDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Disconnect: wipe the secret and stop every sync (integrations.manage)")
    def delete(self, request, org_id, connection_id):
        from jobs.models import Job

        org, err = _gate(request, org_id)
        if err:
            return err
        if not _manager(request, org):
            return Response({"error": "permission_denied", "details": "Missing permission: integrations.manage"}, status=403)
        conn = get_object_or_404(Connection, pk=connection_id, org=org)
        Connection.objects.filter(pk=conn.pk).update(status=Connection.REVOKED, secret_ciphertext=None)
        Job.objects.filter(kind=JOB, status=Job.STATUS_QUEUED, payload__connection_id=str(conn.id)).update(
            status=Job.STATUS_FAILED, last_error="disconnected"
        )
        audit(request.user, "integration.disconnect", target=conn, payload={"connector": conn.connector}, request=request, org=org)
        return Response(status=204)


class ConnectionSyncView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Sync now (integrations.manage)")
    def post(self, request, org_id, connection_id):
        from jobs.queue import enqueue

        org, err = _gate(request, org_id)
        if err:
            return err
        if not _manager(request, org):
            return Response({"error": "permission_denied", "details": "Missing permission: integrations.manage"}, status=403)
        conn = get_object_or_404(Connection, pk=connection_id, org=org, status=Connection.ACTIVE)
        enqueue(JOB, {"connection_id": str(conn.id)})
        conn.refresh_from_db()
        return Response(_connection_payload(conn))


def _item_payload(i):
    return {"id": str(i.id), "kind": i.kind, "external_id": i.external_id, "title": i.title, "url": i.url, "state": i.state, "connector": i.connection.connector}


def visible_items(user, org):
    return ExternalItem.objects.filter(org=org, connection__status=Connection.ACTIVE, connection__room__in=accessible_rooms(user, org)).select_related("connection")


class ItemListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Imported items I can see (search with ?q=)")
    def get(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        qs = visible_items(request.user, org)
        q = (request.query_params.get("q") or "").strip()[:100]
        if q:
            qs = qs.filter(title__icontains=q)
        return Response([_item_payload(i) for i in qs.order_by("-updated_at")[:100]])


class TaskLinkView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _task(self, request, org, task_id):
        from tasks.models import Task

        task = Task.objects.filter(org=org, pk=task_id).first()
        return task if task and can(request.user, "task.view", task.team or org) else None

    @extend_schema(summary="External items linked to a task (only those I can see)")
    def get(self, request, org_id, task_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        task = self._task(request, org, task_id)
        if task is None:
            return Response({"error": "not_found"}, status=404)
        visible = visible_items(request.user, org)
        links = TaskLink.objects.filter(task=task, item__in=visible).select_related("item", "item__connection")
        return Response([{"id": str(link.id), "item": _item_payload(link.item)} for link in links])

    @extend_schema(summary="Link an item I can see to a task (task.write)")
    def post(self, request, org_id, task_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        task = self._task(request, org, task_id)
        if task is None or not can(request.user, "task.write", task.team or org):
            return Response({"error": "not_found"}, status=404)
        item = visible_items(request.user, org).filter(pk=_uuid(_body(request).get("item"))).first()
        if item is None:
            return Response({"error": "not_found", "details": "Item not found"}, status=404)
        link, _ = TaskLink.objects.get_or_create(task=task, item=item, defaults={"created_by": request.user})
        return Response({"id": str(link.id), "item": _item_payload(item)}, status=201)
