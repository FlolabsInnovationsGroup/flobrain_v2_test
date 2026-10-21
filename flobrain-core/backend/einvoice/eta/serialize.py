"""ETA JSON text and the canonical serialization the issuer signs.

The ETA SDK ("Document Serialization Approach", sdk.invoicing.eta.gov.eg):
- start from the document object (not the ``documents`` submission array) and walk it in order;
- every property name is upper-cased (culture-invariant) and written in double quotes;
- a simple value is written in double quotes exactly as it appears in the document (no
  normalization: ``14.00`` stays ``14.00``);
- an object is the sequence of ``"NAME"`` + serialized value of its properties;
- an array is ``"NAME"`` once, then ``"NAME"`` + serialized element for every element;
- the issuer signature covers the whole document except ``signatures``.
The serialized string is hashed with SHA-256 over its UTF-8 bytes and signed as CAdES-BES.

Because values are taken "as they appear", we write the JSON ourselves: Decimal values come out
as the exact number text that ``canonical`` uses, and strings are refused if they hold a double
quote, a backslash or a control character (in JSON they would be escaped and the SDK leaves it
open whether the escaped or the plain form is serialized). Non-ASCII text (Arabic) is written as
UTF-8, not ``\\u`` escapes, so both forms are the same.
"""

import hashlib
import json
import re
from decimal import Decimal

from einvoice.money import fmt_eta

UNSAFE_RE = re.compile(r'["\\\x00-\x1f\x7f]')


class SerializeError(ValueError):
    pass


def number(value) -> str:
    return fmt_eta(value) if isinstance(value, Decimal) else str(value)


def _check(text: str, path: str) -> str:
    if UNSAFE_RE.search(text):
        raise SerializeError(f"{path}: remove quotes, backslashes and line breaks")
    return text


def to_json(value, path="document") -> str:
    """Compact JSON text, key order kept, Decimals as exact numbers."""
    if isinstance(value, dict):
        return "{" + ",".join(f"{json.dumps(_check(str(k), path), ensure_ascii=False)}:{to_json(v, f'{path}.{k}')}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(to_json(v, f"{path}[{i}]") for i, v in enumerate(value)) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (Decimal, int)):
        return number(value)
    if value is None:
        return "null"
    return json.dumps(_check(str(value), path), ensure_ascii=False)


def _simple(value) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (Decimal, int)):
        text = number(value)
    elif value is None:
        text = ""
    else:
        text = str(value)
    return f'"{text}"'


def canonical(document: dict, *, skip=("signatures",)) -> str:
    def walk(value) -> str:
        if isinstance(value, dict):
            out = []
            for key, item in value.items():
                if key in skip and value is document:
                    continue
                name = f'"{str(key).upper()}"'
                if isinstance(item, list):
                    out.append(name + "".join(name + walk(element) for element in item))
                else:
                    out.append(name + walk(item))
            return "".join(out)
        return _simple(value)

    return walk(document)


class _Raw(str):
    """A number kept as its JSON text."""


def canonical_from_json(text: str) -> str:
    """Canonical form of a stored document's JSON text (numbers kept exactly as written)."""
    return canonical(json.loads(text, parse_float=_Raw, parse_int=_Raw))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
