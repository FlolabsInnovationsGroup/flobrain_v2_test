"""Data buddy API (W3). Every endpoint: active member (403) → flag ``data_buddy`` (501, like other V2 features) → permission.

- ``GET  /orgs/{org}/data/meta``: limits, who can add sources, the private-host setting
- ``PATCH /orgs/{org}/data/settings``: ``{allow_private_hosts}`` (org owner or admin with ``data.manage``)
- ``GET  /orgs/{org}/data/datasets``: datasets you can see (``data.use``)
- ``POST /orgs/{org}/data/datasets/upload`` (multipart ``file``), ``.../sheet`` ``{url}``,
  ``.../postgres`` ``{dsn, tables?}``: add a source (``data.manage``); common fields
  ``name, description, visibility (org|team|owner), team``
- ``GET|PATCH|DELETE /orgs/{org}/data/datasets/{id}``; ``POST .../{id}/refresh``
- ``POST /orgs/{org}/data/ask`` ``{dataset_id, question}``: SQL, rows (capped), chart, answer
- ``GET|POST /orgs/{org}/data/cards``; ``PATCH|DELETE .../cards/{id}``; ``POST .../cards/{id}/run``
- ``GET|POST /orgs/{org}/data/reports``; ``PATCH|DELETE .../reports/{id}``; ``POST .../reports/{id}/run``
"""

import uuid

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied, Throttled
from rest_framework.response import Response

from brain.throttles import AISendThrottle
from core_v2.views import V2APIView
from datasets import ingest, pg, services, sheets
from datasets.models import Dataset, Report, SavedQuestion
from datasets.services import DataError
from organizations.models import Organization, Team
from organizations.permissions import IsActiveOrgMember, can, is_org_owner_or_admin
from organizations.services.core import audit

MAX_TITLE = 160


def _err(code, details, status=400, **extra):
    return Response({"error": code, "details": details, **extra}, status=status)


def _from_error(exc: DataError):
    return _err(exc.code, exc.details, exc.status, **exc.extra)


def _body(request):
    return request.data if hasattr(request.data, "get") else {}


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


class DataView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def gate(self, request, org_id, perm="data.use"):
        """Return (org, error). Flag off is a 501, which the frontend shows as switched off."""
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        if not services.flag_on(request.user, org):
            return org, _err("not_implemented", "Data buddy is not enabled", 501)
        if perm and not can(request.user, perm, org):
            raise PermissionDenied(f"Missing permission: {perm}")
        return org, None

    def dataset(self, request, org, dataset_id):
        return services.visible_datasets(request.user, org).filter(pk=dataset_id).first()

    def throttle_ai(self, request):
        throttle = AISendThrottle()
        if not throttle.allow_request(request, self):
            raise Throttled(wait=throttle.wait())


def _sharing(request, org, data, current=None):
    """Validate visibility + team. Returns (visibility, team) or raises DataError."""
    visibility = data.get("visibility", current.visibility if current else Dataset.VISIBILITY_OWNER)
    if visibility not in (Dataset.VISIBILITY_ORG, Dataset.VISIBILITY_TEAM, Dataset.VISIBILITY_OWNER):
        raise DataError("invalid", "visibility must be org, team or owner")
    team = current.team if current else None
    if "team" in data or visibility == Dataset.VISIBILITY_TEAM:
        team_id = _uuid(data.get("team")) if data.get("team") else (current.team_id if current else None)
        team = Team.objects.filter(org=org, pk=team_id, is_active=True).first() if team_id else None
    if visibility == Dataset.VISIBILITY_TEAM:
        if team is None:
            raise DataError("invalid", "Pick a team to share with")
        if not is_org_owner_or_admin(request.user, org) and not team.memberships.filter(user=request.user).exists():
            raise DataError("invalid", "You can only share with a team you are in")
    else:
        team = None
    return visibility, team


def _new_dataset(request, org, data, kind) -> Dataset:
    name = " ".join(str(data.get("name") or "").split())[:120]
    if not name:
        raise DataError("invalid", "Give the dataset a name")
    services.check_quota(org)
    visibility, team = _sharing(request, org, data)
    return Dataset(
        id=uuid.uuid4(), org=org, owner=request.user, name=name, kind=kind,
        description=str(data.get("description") or "")[:500], visibility=visibility, team=team,
    )


class MetaView(DataView):
    @extend_schema(summary="Data buddy limits and settings")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        from integrations import crypto

        return Response({
            "can_manage": can(request.user, "data.manage", org),
            "is_admin": is_org_owner_or_admin(request.user, org),
            "allow_private_hosts": services.allow_private_hosts(org),
            "postgres_available": crypto.is_configured(),
            "max_upload_mb": ingest.max_bytes() // (1024 * 1024),
            "max_rows": ingest.max_rows(),
            "query_max_rows": services.row_limit(),
            "query_seconds": services.time_limit(),
        })


class SettingsView(DataView):
    @extend_schema(summary="Allow or block private network hosts for PostgreSQL sources")
    def patch(self, request, org_id):
        org, error = self.gate(request, org_id, "data.manage")
        if error:
            return error
        if not is_org_owner_or_admin(request.user, org):
            raise PermissionDenied("Only an org owner or admin can change this")
        data = _body(request)
        if not isinstance(data.get("allow_private_hosts"), bool):
            return _err("invalid", "allow_private_hosts must be true or false")
        with transaction.atomic():
            org = Organization.objects.select_for_update().get(pk=org.pk)
            settings_ = dict(org.settings or {})
            section = dict(settings_.get("data_buddy") or {})
            section["allow_private_hosts"] = data["allow_private_hosts"]
            settings_["data_buddy"] = section
            org.settings = settings_
            org.save(update_fields=["settings"])
        audit(request.user, "data.settings", target=org, payload={"allow_private_hosts": data["allow_private_hosts"]}, request=request, org=org)
        return Response({"allow_private_hosts": data["allow_private_hosts"]})


class DatasetListView(DataView):
    @extend_schema(summary="Datasets you can see")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        rows = services.visible_datasets(request.user, org).order_by("name")[:200]
        return Response([services.dataset_payload(ds, request.user) for ds in rows])


class UploadView(DataView):
    @extend_schema(summary="Add a dataset from a CSV or XLSX file")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, "data.manage")
        if error:
            return error
        upload = request.FILES.get("file")
        if upload is None:
            return _err("invalid", "Attach a .csv or .xlsx file")
        if upload.size > ingest.max_bytes():
            return _err("too_large", f"Files can be at most {ingest.max_bytes() // (1024 * 1024)} MB", 413)
        data = _body(request)
        try:
            ds = _new_dataset(request, org, {**{k: data.get(k) for k in data}, "name": data.get("name") or upload.name.rsplit(".", 1)[0]}, Dataset.KIND_UPLOAD)
            columns, rows = ingest.parse_file(upload.name, upload.read(ingest.max_bytes() + 1))
        except DataError as exc:
            return _from_error(exc)
        except ingest.IngestError as exc:
            return _err(exc.code, exc.details, 413 if exc.code == "too_large" else 400)
        ds.source_name = upload.name[:200]
        services.store_rows(ds, columns, rows)
        ds.save()
        audit(request.user, "data.dataset.create", target=ds, payload={"kind": ds.kind, "rows": ds.row_count}, request=request, org=org)
        return Response(services.dataset_payload(ds, request.user), status=201)


class SheetView(DataView):
    @extend_schema(summary="Add a Google Sheet published to the web as CSV")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, "data.manage")
        if error:
            return error
        data = _body(request)
        try:
            hours = int(data.get("refresh_every_hours", 24) or 0)
        except (TypeError, ValueError):
            hours = -1
        if hours not in (0, 1, 6, 12, 24, 168):
            return _err("invalid", "refresh_every_hours must be 0, 1, 6, 12, 24 or 168")
        try:
            url = sheets.normalize_url(data.get("url"))
            ds = _new_dataset(request, org, data, Dataset.KIND_SHEET)
            ds.sheet_url, ds.refresh_every_hours, ds.source_name = url, hours, "Google Sheet"
            services.refresh_sheet(ds)
        except sheets.SheetError as exc:
            return _err(exc.code, exc.details)
        except DataError as exc:
            return _from_error(exc)
        services.schedule_next_refresh(ds)
        ds.save()
        audit(request.user, "data.dataset.create", target=ds, payload={"kind": ds.kind, "rows": ds.row_count}, request=request, org=org)
        return Response(services.dataset_payload(ds, request.user), status=201)


class PostgresView(DataView):
    @extend_schema(summary="Connect a PostgreSQL database read-only")
    def post(self, request, org_id):
        from integrations import crypto

        org, error = self.gate(request, org_id, "data.manage")
        if error:
            return error
        if not crypto.is_configured():
            return _err("not_configured", "Credential encryption is not configured", 501)
        data = _body(request)
        dsn = data.get("dsn")
        tables = data.get("tables")
        if tables is not None and (not isinstance(tables, list) or not all(isinstance(t, str) and t for t in tables) or len(tables) > pg.MAX_TABLES):
            return _err("invalid", f"tables must be a list of up to {pg.MAX_TABLES} names")
        try:
            pg.parse_dsn(dsn)
            ds = _new_dataset(request, org, data, Dataset.KIND_POSTGRES)
            services.refresh_postgres(ds, wanted=tables, dsn=dsn)
        except pg.DSNError as exc:
            return _err(exc.code, exc.details)
        except DataError as exc:
            return _from_error(exc)
        services.set_dsn(ds, dsn)
        ds.source_name = "PostgreSQL"
        ds.save()
        audit(request.user, "data.dataset.create", target=ds, payload={"kind": ds.kind, "tables": len(ds.tables)}, request=request, org=org)
        return Response(services.dataset_payload(ds, request.user), status=201)


class DatasetDetailView(DataView):
    @extend_schema(summary="One dataset with its schema and sample rows")
    def get(self, request, org_id, dataset_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        ds = self.dataset(request, org, dataset_id)
        if ds is None:
            return _err("not_found", "Dataset not found", 404)
        data = services.dataset_payload(ds, request.user)
        data["cards"] = [services.card_payload(c) for c in ds.cards.select_related("dataset")[:100]]
        return Response(data)

    @extend_schema(summary="Rename, re-share or change the refresh schedule")
    def patch(self, request, org_id, dataset_id):
        org, error = self.gate(request, org_id, "data.manage")
        if error:
            return error
        ds = self.dataset(request, org, dataset_id)
        if ds is None:
            return _err("not_found", "Dataset not found", 404)
        if not services.can_manage(request.user, ds):
            raise PermissionDenied("Only the owner or an admin can change this dataset")
        data = _body(request)
        try:
            if "name" in data:
                name = " ".join(str(data.get("name") or "").split())[:120]
                if not name:
                    raise DataError("invalid", "Give the dataset a name")
                ds.name = name
            if "description" in data:
                ds.description = str(data.get("description") or "")[:500]
            if "visibility" in data or "team" in data:
                ds.visibility, ds.team = _sharing(request, org, data, ds)
            if "refresh_every_hours" in data and ds.kind == Dataset.KIND_SHEET:
                try:
                    hours = int(data.get("refresh_every_hours") or 0)
                except (TypeError, ValueError):
                    hours = -1
                if hours not in (0, 1, 6, 12, 24, 168):
                    raise DataError("invalid", "refresh_every_hours must be 0, 1, 6, 12, 24 or 168")
                ds.refresh_every_hours = hours
                services.schedule_next_refresh(ds)
        except DataError as exc:
            return _from_error(exc)
        ds.save()
        audit(request.user, "data.dataset.update", target=ds, payload={"visibility": ds.visibility}, request=request, org=org)
        return Response(services.dataset_payload(ds, request.user))

    @extend_schema(summary="Delete a dataset, its data file, cards and report entries")
    def delete(self, request, org_id, dataset_id):
        org, error = self.gate(request, org_id, "data.manage")
        if error:
            return error
        ds = self.dataset(request, org, dataset_id)
        if ds is None:
            return _err("not_found", "Dataset not found", 404)
        if not services.can_manage(request.user, ds):
            raise PermissionDenied("Only the owner or an admin can delete this dataset")
        audit(request.user, "data.dataset.delete", target=ds, payload={"kind": ds.kind}, request=request, org=org)
        services.delete_dataset_files(ds)
        ds.delete()
        return Response(status=204)


class RefreshView(DataView):
    @extend_schema(summary="Fetch a sheet again, or re-read a database's tables")
    def post(self, request, org_id, dataset_id):
        org, error = self.gate(request, org_id, "data.manage")
        if error:
            return error
        ds = self.dataset(request, org, dataset_id)
        if ds is None:
            return _err("not_found", "Dataset not found", 404)
        if not services.can_manage(request.user, ds):
            raise PermissionDenied("Only the owner or an admin can refresh this dataset")
        try:
            if ds.kind == Dataset.KIND_SHEET:
                services.refresh_sheet(ds)
                services.schedule_next_refresh(ds)
            elif ds.kind == Dataset.KIND_POSTGRES:
                services.refresh_postgres(ds)
            else:
                return _err("not_refreshable", "Upload the file again to update it", 409)
        except DataError as exc:
            if exc.code != "demo":
                ds.status, ds.last_error = Dataset.STATUS_ERROR, exc.details[:300]
                ds.save(update_fields=["status", "last_error", "updated_at"])
            return _from_error(exc)
        ds.save()
        return Response(services.dataset_payload(ds, request.user))


class AskView(DataView):
    @extend_schema(summary="Ask a question in plain language: SQL, rows, chart and answer")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        data = _body(request)
        dataset_id = _uuid(data.get("dataset_id"))
        ds = self.dataset(request, org, dataset_id) if dataset_id else None
        if ds is None:
            return _err("not_found", "Dataset not found", 404)
        question = str(data.get("question") or "").strip()
        if not question or len(question) > 500:
            return _err("invalid", "Ask a question of at most 500 characters")
        self.throttle_ai(request)
        try:
            result = services.ask(request.user, org, ds, question)
        except DataError as exc:
            return _from_error(exc)
        audit(request.user, "data.ask", target=ds, payload={"rows": result.get("row_count", 0)}, request=request, org=org)
        return Response(result)


def _clean_chart(data):
    chart = data.get("chart")
    return chart if isinstance(chart, dict) else {}


class CardListView(DataView):
    @extend_schema(summary="Saved questions (cards) on datasets you can see")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        cards = services.visible_cards(request.user, org)
        dataset = _uuid(request.query_params.get("dataset"))
        if dataset:
            cards = cards.filter(dataset_id=dataset)
        return Response([services.card_payload(c) for c in cards[:200]])

    @extend_schema(summary="Save a question as a card (its SQL is checked and run again)")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        data = _body(request)
        dataset_id = _uuid(data.get("dataset_id") or data.get("dataset"))
        ds = self.dataset(request, org, dataset_id) if dataset_id else None
        if ds is None:
            return _err("not_found", "Dataset not found", 404)
        title = " ".join(str(data.get("title") or data.get("question") or "").split())[:MAX_TITLE]
        if not title:
            return _err("invalid", "Give the card a title")
        card = SavedQuestion(
            org=org, dataset=ds, created_by=request.user, title=title,
            question=str(data.get("question") or "")[:500], sql=str(data.get("sql") or ""),
            chart=_clean_chart(data), answer=str(data.get("answer") or "")[:1500],
        )
        try:
            result = services.run_sql(ds, card.sql)
        except DataError as exc:
            return _from_error(exc)
        card.sql = services.clean_sql(ds, card.sql)
        services.apply_result(card, result)
        card.save()
        audit(request.user, "data.card.create", target=card, payload={"dataset": str(ds.id)}, request=request, org=org)
        return Response(services.card_payload(card), status=201)


class CardDetailView(DataView):
    def card(self, request, org, card_id):
        return services.visible_cards(request.user, org).filter(pk=card_id).first()

    def _editable(self, request, org, card):
        if card.created_by_id != request.user.id and not services.can_manage(request.user, card.dataset):
            raise PermissionDenied("Only the person who saved it or the dataset's manager can change it")

    @extend_schema(summary="Rename a card or change its chart")
    def patch(self, request, org_id, card_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        card = self.card(request, org, card_id)
        if card is None:
            return _err("not_found", "Card not found", 404)
        self._editable(request, org, card)
        data = _body(request)
        if "title" in data:
            title = " ".join(str(data.get("title") or "").split())[:MAX_TITLE]
            if not title:
                return _err("invalid", "Give the card a title")
            card.title = title
        if "chart" in data:
            columns = (card.last_result or {}).get("columns") or []
            rows = (card.last_result or {}).get("rows") or []
            chart, fixed = services.validate_chart(_clean_chart(data), columns, rows)
            if fixed:
                return _err("invalid", "That chart does not match the card's columns")
            card.chart = chart
        card.save()
        return Response(services.card_payload(card))

    @extend_schema(summary="Delete a card")
    def delete(self, request, org_id, card_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        card = self.card(request, org, card_id)
        if card is None:
            return _err("not_found", "Card not found", 404)
        self._editable(request, org, card)
        audit(request.user, "data.card.delete", target=card, payload={}, request=request, org=org)
        card.delete()
        return Response(status=204)


class CardRunView(DataView):
    @extend_schema(summary="Run a card's SQL again for fresh numbers")
    def post(self, request, org_id, card_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        card = services.visible_cards(request.user, org).filter(pk=card_id).first()
        if card is None:
            return _err("not_found", "Card not found", 404)
        try:
            services.run_card(card)
        except DataError as exc:
            return _from_error(exc)
        return Response(services.card_payload(card))


def _report_fields(request, org, data, report=None):
    """Validate report fields. Returns a dict of plain fields plus cards/recipients/room."""
    out = {}
    if report is None or "name" in data:
        name = " ".join(str(data.get("name") or "").split())[:120]
        if not name:
            raise DataError("invalid", "Give the report a name")
        out["name"] = name
    if report is None or "cadence" in data:
        cadence = data.get("cadence", Report.CADENCE_WEEKLY)
        if cadence not in (Report.CADENCE_WEEKLY, Report.CADENCE_MONTHLY):
            raise DataError("invalid", "cadence must be weekly or monthly")
        out["cadence"] = cadence
    for key, low, high in (("weekday", 0, 6), ("day_of_month", 1, 28), ("hour", 0, 23)):
        if key in data:
            try:
                value = int(data[key])
            except (TypeError, ValueError):
                value = -1
            if not low <= value <= high:
                raise DataError("invalid", f"{key} must be between {low} and {high}")
            out[key] = value
    if "enabled" in data:
        out["enabled"] = bool(data["enabled"])
    if report is None or "cards" in data:
        ids = data.get("cards") or []
        if not isinstance(ids, list) or not ids or len(ids) > 20:
            raise DataError("invalid", "Pick between 1 and 20 cards")
        wanted = {_uuid(i) for i in ids} - {None}
        cards = list(services.visible_cards(request.user, org).filter(pk__in=wanted))
        if len(cards) != len(wanted) or len(wanted) != len(ids):
            raise DataError("not_found", "A card was not found", 404)
        out["cards"] = cards
    if "recipients" in data:
        from organizations.models import OrgMembership

        ids = data.get("recipients") or []
        if not isinstance(ids, list) or len(ids) > 50:
            raise DataError("invalid", "recipients must be a list of up to 50 members")
        wanted = {_uuid(i) for i in ids} - {None}
        members = list(OrgMembership.objects.filter(org=org, user_id__in=wanted, employment_status="active").select_related("user"))
        if len(members) != len(wanted):
            raise DataError("not_found", "A recipient is not an active member", 404)
        out["recipients"] = [m.user for m in members]
    if "room" in data:
        out["room"] = None
        if data.get("room"):
            from rooms.models import Room
            from rooms.services import user_can_access_room

            room = Room.objects.filter(org=org, pk=_uuid(data.get("room"))).first()
            if room is None or not user_can_access_room(request.user, room) or not can(request.user, "chat.use", org):
                raise DataError("not_found", "Room not found", 404)
            out["room"] = room
    return out


class ReportListView(DataView):
    def reports(self, request, org):
        qs = Report.objects.filter(org=org).prefetch_related("cards", "recipients", "runs")
        if not is_org_owner_or_admin(request.user, org):
            qs = qs.filter(created_by=request.user) | qs.filter(recipients=request.user)
        return qs.distinct()

    @extend_schema(summary="Scheduled reports you made or receive")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        return Response([services.report_payload(r) for r in self.reports(request, org)[:100]])

    @extend_schema(summary="Schedule a weekly or monthly report from cards")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        try:
            fields = _report_fields(request, org, _body(request))
        except DataError as exc:
            return _from_error(exc)
        cards, recipients = fields.pop("cards"), fields.pop("recipients", [])
        report = Report(org=org, created_by=request.user, **fields)
        report.next_run_at = services.next_run(report, timezone.now())
        report.save()
        report.cards.set(cards)
        report.recipients.set(recipients)
        audit(request.user, "data.report.create", target=report, payload={"cards": len(cards), "cadence": report.cadence}, request=request, org=org)
        return Response(services.report_payload(report), status=201)


class ReportDetailView(DataView):
    def report(self, request, org, report_id):
        report = Report.objects.filter(org=org, pk=report_id).first()
        if report is None:
            return None
        if report.created_by_id != request.user.id and not is_org_owner_or_admin(request.user, org):
            return None
        return report

    @extend_schema(summary="Change a report's cards, schedule, recipients or room")
    def patch(self, request, org_id, report_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        report = self.report(request, org, report_id)
        if report is None:
            return _err("not_found", "Report not found", 404)
        try:
            fields = _report_fields(request, org, _body(request), report)
        except DataError as exc:
            return _from_error(exc)
        cards, recipients = fields.pop("cards", None), fields.pop("recipients", None)
        for key, value in fields.items():
            setattr(report, key, value)
        report.next_run_at = services.next_run(report, timezone.now())
        report.save()
        if cards is not None:
            report.cards.set(cards)
        if recipients is not None:
            report.recipients.set(recipients)
        return Response(services.report_payload(report))

    @extend_schema(summary="Delete a report")
    def delete(self, request, org_id, report_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        report = self.report(request, org, report_id)
        if report is None:
            return _err("not_found", "Report not found", 404)
        audit(request.user, "data.report.delete", target=report, payload={}, request=request, org=org)
        report.delete()
        return Response(status=204)


class ReportRunView(DataView):
    @extend_schema(summary="Send a report now with fresh numbers")
    def post(self, request, org_id, report_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        report = ReportDetailView.report(self, request, org, report_id)
        if report is None:
            return _err("not_found", "Report not found", 404)
        run = services.run_report(report)
        return Response({**services.report_payload(report), "run": {"status": run.status, "notified": run.notified, "posted_to_room": run.posted_to_room}})
