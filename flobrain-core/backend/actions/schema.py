"""A small, strict JSON-schema subset for tool arguments.

Supported: object (properties, required, additionalProperties: false), string
(minLength, maxLength, enum, format uuid|date|date-time|email), integer
(minimum, maximum), boolean, array (items, maxItems). Anything else in the
arguments is refused. Returns cleaned values (UUIDs normalized, dates parsed
to ISO strings).
"""

import re
import uuid

from django.utils.dateparse import parse_date, parse_datetime

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")


class SchemaError(ValueError):
    pass


def validate(schema: dict, value, path="arguments"):
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise SchemaError(f"{path} must be an object")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                raise SchemaError(f"{path} has unknown fields: {', '.join(sorted(extra))}")
        for name in schema.get("required", []):
            if value.get(name) in (None, ""):
                raise SchemaError(f"{path}.{name} is required")
        out = {}
        for name, sub in props.items():
            if name in value and value[name] is not None:
                out[name] = validate(sub, value[name], f"{path}.{name}")
        return out
    if kind == "string":
        if not isinstance(value, str):
            raise SchemaError(f"{path} must be a string")
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 100_000):
            raise SchemaError(f"{path} has the wrong length")
        if "enum" in schema and value not in schema["enum"]:
            raise SchemaError(f"{path} must be one of {', '.join(schema['enum'])}")
        fmt = schema.get("format")
        if fmt == "uuid":
            try:
                return str(uuid.UUID(value))
            except ValueError as exc:
                raise SchemaError(f"{path} must be an id") from exc
        if fmt == "date":
            try:
                parsed = parse_date(value)
            except ValueError:
                parsed = None
            if parsed is None:
                raise SchemaError(f"{path} must be a date (YYYY-MM-DD)")
            return parsed.isoformat()
        if fmt == "date-time":
            try:
                parsed = parse_datetime(value)
            except ValueError:
                parsed = None
            if parsed is None:
                raise SchemaError(f"{path} must be an ISO date-time")
            return parsed.isoformat()
        if fmt == "email" and not EMAIL_RE.match(value):
            raise SchemaError(f"{path} must be an email address")
        return value
    if kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise SchemaError(f"{path} must be an integer")
        if value < schema.get("minimum", -(2**31)) or value > schema.get("maximum", 2**31):
            raise SchemaError(f"{path} is out of range")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise SchemaError(f"{path} must be true or false")
        return value
    if kind == "array":
        if not isinstance(value, list):
            raise SchemaError(f"{path} must be a list")
        if len(value) > schema.get("maxItems", 100):
            raise SchemaError(f"{path} has too many items")
        return [validate(schema.get("items", {}), item, f"{path}[{i}]") for i, item in enumerate(value)]
    raise SchemaError(f"{path}: unsupported schema")
