"""Input checks for eval sets, cases and the org eval policy. Raise ``CaseInvalid`` with a plain message."""

import uuid
from decimal import Decimal, InvalidOperation

MAX_INPUT = 4000
MAX_RUBRIC = 2000
MAX_PHRASES = 10
MAX_PHRASE = 200
MAX_DOCS = 5
LANGUAGES = ("any", "ar", "en")


class CaseInvalid(Exception):
    pass


def _phrases(value, field):
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > MAX_PHRASES:
        raise CaseInvalid(f"{field} must be a list of at most {MAX_PHRASES} phrases")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > MAX_PHRASE:
            raise CaseInvalid(f"each phrase in {field} needs 1 to {MAX_PHRASE} characters")
        out.append(item.strip())
    return list(dict.fromkeys(out))


def _tool(value, field):
    from actions.registry import TOOLS

    key = str(value or "").strip()
    if key in ("", "none") or key in TOOLS:
        return key
    raise CaseInvalid(f"{field} must be an action key, none, or empty")


def _docs(value, user, org, check):
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > MAX_DOCS:
        raise CaseInvalid(f"context_doc_ids must list at most {MAX_DOCS} documents")
    try:
        ids = list(dict.fromkeys(str(uuid.UUID(str(v))) for v in value))
    except ValueError as exc:
        raise CaseInvalid("context_doc_ids must be document ids") from exc
    if check and ids:
        from docs_app.models import Document
        from rooms.services import accessible_rooms

        rooms = accessible_rooms(user, org).values("pk")
        found = {str(pk) for pk in Document.objects.filter(org=org, pk__in=ids, room__in=rooms).values_list("pk", flat=True)}
        if set(ids) - found:
            raise CaseInvalid("you can only add documents you can open")
    return ids


def clean_case(data, user, org, check_docs=True, partial=False) -> dict:
    if not isinstance(data, dict):
        raise CaseInvalid("a case must be an object")
    out = {}
    if not partial or "input" in data:
        text = data.get("input")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_INPUT:
            raise CaseInvalid(f"input is required (at most {MAX_INPUT} characters)")
        out["input"] = text.strip()
    if "name" in data:
        name = data.get("name") or ""
        if not isinstance(name, str) or len(name) > 120:
            raise CaseInvalid("name has at most 120 characters")
        out["name"] = name.strip()
    if "context_doc_ids" in data:
        out["context_doc_ids"] = _docs(data.get("context_doc_ids"), user, org, check_docs)
    for field in ("must_include", "must_not_include"):
        if field in data:
            out[field] = _phrases(data.get(field), field)
    if "must_cite" in data:
        if not isinstance(data.get("must_cite"), bool):
            raise CaseInvalid("must_cite must be true or false")
        out["must_cite"] = data["must_cite"]
    if "expected_tool" in data:
        out["expected_tool"] = _tool(data.get("expected_tool"), "expected_tool")
    if "forbidden_tools" in data:
        tools = data.get("forbidden_tools") or []
        if not isinstance(tools, list) or len(tools) > 20:
            raise CaseInvalid("forbidden_tools must be a list of action keys")
        cleaned = [_tool(t, "forbidden_tools") for t in tools]
        if any(t in ("", "none") for t in cleaned):
            raise CaseInvalid("forbidden_tools must be a list of action keys")
        out["forbidden_tools"] = list(dict.fromkeys(cleaned))
    if "max_words" in data:
        words = data.get("max_words")
        if words in (None, ""):
            out["max_words"] = None
        elif isinstance(words, bool) or not isinstance(words, int) or not 1 <= words <= 5000:
            raise CaseInvalid("max_words must be a whole number from 1 to 5000")
        else:
            out["max_words"] = words
    if "language" in data:
        language = data.get("language") or "any"
        if language not in LANGUAGES:
            raise CaseInvalid("language must be ar, en or any")
        out["language"] = language
    if "rubric" in data:
        rubric = data.get("rubric") or ""
        if not isinstance(rubric, str) or len(rubric) > MAX_RUBRIC:
            raise CaseInvalid(f"rubric has at most {MAX_RUBRIC} characters")
        out["rubric"] = rubric.strip()
    if "position" in data:
        position = data.get("position")
        if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position <= 10000:
            raise CaseInvalid("position must be a whole number")
        out["position"] = position
    if out.get("expected_tool") and out["expected_tool"] != "none" and out["expected_tool"] in out.get("forbidden_tools", []):
        raise CaseInvalid("an action cannot be both expected and forbidden")
    return out


def _int(data, field, low, high):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CaseInvalid(f"{field} must be a whole number from {low} to {high}")
    return value


def clean_set(data, partial=False) -> dict:
    from evals.models import EvalSet

    if not isinstance(data, dict):
        raise CaseInvalid("send an object")
    out = {}
    if not partial or "name" in data:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise CaseInvalid("name is required (at most 120 characters)")
        out["name"] = name.strip()
    if "description" in data:
        desc = data.get("description") or ""
        if not isinstance(desc, str) or len(desc) > 500:
            raise CaseInvalid("description has at most 500 characters")
        out["description"] = desc.strip()
    if "threshold" in data:
        out["threshold"] = _int(data, "threshold", 0, 100)
    if "max_drop" in data:
        out["max_drop"] = _int(data, "max_drop", 0, 100)
    for field in ("gate_marketplace", "gate_saves"):
        if field in data:
            if not isinstance(data.get(field), bool):
                raise CaseInvalid(f"{field} must be true or false")
            out[field] = data[field]
    if "schedule" in data:
        if data.get("schedule") not in dict(EvalSet.SCHEDULE_CHOICES):
            raise CaseInvalid("schedule must be off, daily or weekly")
        out["schedule"] = data["schedule"]
    return out


def clean_policy(data) -> dict:
    from brain.llm.direct import allowlist

    if not isinstance(data, dict):
        raise CaseInvalid("send an object")
    out = {}
    if "judge_model" in data:
        model = str(data.get("judge_model") or "").strip()
        if model and model not in allowlist():
            raise CaseInvalid("judge_model must be one of the models your platform allows, or empty")
        out["judge_model"] = model
    if "max_run_tokens" in data:
        out["max_run_tokens"] = _int(data, "max_run_tokens", 1000, 2_000_000)
    if "max_run_cost" in data:
        raw = data.get("max_run_cost")
        if raw in (None, ""):
            out["max_run_cost"] = None
        else:
            try:
                cost = Decimal(str(raw))
            except InvalidOperation as exc:
                raise CaseInvalid("max_run_cost must be an amount") from exc
            if not cost.is_finite() or cost <= 0 or cost > 1000:
                raise CaseInvalid("max_run_cost must be more than 0 and at most 1000")
            out["max_run_cost"] = cost.quantize(Decimal("0.0001"))
    if "concurrency" in data:
        out["concurrency"] = _int(data, "concurrency", 1, 8)
    return out
