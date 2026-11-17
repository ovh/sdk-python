# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Building requests: path parameters, query and header values, JSON bodies."""

from __future__ import annotations

import base64
import dataclasses
import datetime
import decimal
import enum
import json
import math
import re
import typing as t
from urllib.parse import quote, unquote, unquote_plus, urlencode

import pydantic

from ._errors import InvalidRequestError
from ._models import dump
from ._types import NOT_GIVEN, NotGiven

if t.TYPE_CHECKING:
    from ._registry import Operation

__all__ = [
    "Request",
    "encode_value",
    "fill_path",
    "path",
    "to_jsonable",
]

# Values a parameter pair may hold: anything encode_value takes.
Pairs: t.TypeAlias = t.Iterable[tuple[str, object]]


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    """One API call, as the client sends it."""

    method: str
    #: The path with its API version, parameters filled in: "/v1/vrack/pn-1".
    path: str
    query: tuple[tuple[str, object], ...] = ()
    headers: tuple[tuple[str, object], ...] = ()
    body: object = NOT_GIVEN
    operation: Operation | None = None
    #: X-Schemas-Version to send, or None.
    schemas_version: str | None = None


# A {name} left in a path. fill_path escapes the braces of every value it fills in, so a
# placeholder left over is a parameter that was never set. Only the part before any query
# string is checked: braces in a query are data.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.-]*)\}")

# What Go's url.PathEscape leaves as it is, apart from letters, digits and "-_.~".
_PATH_SAFE = "$&+:=@"


def fill_path(template: str, params: t.Mapping[str, object]) -> str:
    """Fill the {name} placeholders of a path, escaping each value::

        fill_path("/v1/vrack/{serviceName}/ip/{ip}", {"serviceName": sn, "ip": ip})

    An empty value (or None) leaves its placeholder, and the client then refuses the
    request: GET /v1/vrack/ instead of GET /v1/vrack/{serviceName} would call another route.
    """
    path = template
    for name, value in params.items():
        values = encode_value(value)
        text = values[0] if values else ""
        if not text:
            continue
        path = path.replace("{" + name + "}", quote(text, safe=_PATH_SAFE))
    return path


def path(template: str, /, **params: object) -> str:
    """Fill the {name} placeholders of a path, escaping each value, for the raw calls::

        client.get(ovhcloud.path("/v1/vrack/{serviceName}/ip/{ip}", serviceName=sn, ip=ip))

    Like Go's ``ovh.Path``. Without it, a value such as "1.2.3.0/24" would call another
    route. Values are encoded like query values: an enum gives its value, a datetime its
    RFC 3339 text. An empty value (or None) leaves its placeholder, and the client then
    refuses the request.
    """
    return fill_path(template, params)


# The API version a path starts with: "/v1/me", "/v2/iam/policy".
_VERSIONED = re.compile(r"/v[0-9]+(/|$)")


def check_path(path: str, method: str, operation: Operation | None) -> None:
    """Refuse a path that would not call the route it names.

    Unlike Go, a path without its API version is refused here, with a hint: "/me" or
    "/1.0/me" (the python-ovh form) would get a plain 404 from the API. operation is the
    operation the path matched, if any: it gives the version of the hint.
    """
    # The path is appended to the endpoint as text, so one that does not start with "/"
    # would change the host the request, and its token, go to: "@evil.example/".
    if not path.startswith("/"):
        raise InvalidRequestError(f"path {path!r}: it must start with /")
    route = path.split("?", 1)[0]
    if not _VERSIONED.match(route):
        raise InvalidRequestError(
            f"path {path!r}: it must start with the API version, /v1/ or /v2/:"
            f" did you mean {_versioned(path, operation)}?"
        )
    where = f"{method} {path}"
    if operation is not None:
        where = f"{operation.name} ({where})"
    m = _PLACEHOLDER.search(route)
    if m is not None:
        raise InvalidRequestError(f"{where}: the path parameter {m.group(1)} is empty")
    # httpx removes "." and ".." segments before it sends a request. The route sent would
    # then not be the route that read_only and allowed_operations checked:
    # "/v1/vrack/../ip/x" is sent as "/v1/ip/x". A path parameter set to ".." is the same.
    if any(unquote(segment) in (".", "..") for segment in route.split("/")):
        raise InvalidRequestError(f"{where}: the path has a . or .. segment")


def _versioned(path: str, operation: Operation | None) -> str:
    """path with its API version, for a hint: the version of the operation it matched, or
    /v1."""
    rest = path[len("/1.0") :] if path == "/1.0" or path.startswith(("/1.0/", "/1.0?")) else path
    version = "/v1"
    if operation is not None and operation.path.startswith("/v"):
        version = "/" + operation.path.split("/", 2)[1]
    return version + rest


def encode_value(value: object) -> list[str]:
    """Encode one parameter value as query or header text.

    None and NOT_GIVEN give nothing. A list gives one value per item (the key is repeated).
    A dict or a model is sent as JSON, which is how the API takes object parameters such as
    iamTags. A datetime is sent in RFC 3339.
    """
    if value is None or isinstance(value, NotGiven):
        return []
    if isinstance(value, enum.Enum):
        return encode_value(t.cast("object", value.value))
    if isinstance(value, bool):
        return ["true" if value else "false"]
    if isinstance(value, str):
        return [value]
    if isinstance(value, int):
        return [str(value)]
    if isinstance(value, float):
        return [_format_float(value)]
    if isinstance(value, decimal.Decimal):
        return [format(value, "f")]
    if isinstance(value, datetime.datetime):
        return [_rfc3339(value)]
    if isinstance(value, datetime.date):
        return [value.isoformat()]
    if isinstance(value, (list, tuple, set, frozenset)):
        out: list[str] = []
        for item in t.cast("t.Iterable[object]", value):
            out.extend(encode_value(item))
        return out
    if isinstance(value, t.Mapping) and not t.cast("t.Mapping[object, object]", value):
        return []
    value = t.cast("object", value)
    return [
        json.dumps(to_jsonable(value), separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    ]


def _format_float(f: float) -> str:
    """Go's strconv.FormatFloat(f, 'f', -1, 64): the shortest exact form, no exponent."""
    if math.isnan(f):
        return "NaN"
    if math.isinf(f):
        return "+Inf" if f > 0 else "-Inf"
    text = format(decimal.Decimal(repr(f)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _rfc3339(value: datetime.datetime) -> str:
    """Go's time.RFC3339: seconds precision, "Z" for UTC."""
    _check_aware(value)
    text = value.replace(microsecond=0).isoformat()
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    return text


def _check_aware(value: datetime.datetime) -> None:
    """Refuse a naive datetime: the API would read it in its own time zone. Go's time.Time
    always has one, so this check exists only in Python."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidRequestError(
            f"datetime {value.isoformat()} has no time zone: give one,"
            " datetime.datetime.now(datetime.UTC) or .replace(tzinfo=...)"
        )


def _check_aware_in(value: object) -> None:
    """Refuse a naive datetime anywhere in value: a model, a mapping, a list..."""
    if isinstance(value, datetime.datetime):
        _check_aware(value)
        return
    items: t.Iterable[object]
    if isinstance(value, pydantic.BaseModel):
        set_values = [getattr(value, name, None) for name in value.model_fields_set]
        items = [*set_values, *(value.model_extra or {}).values()]
    elif isinstance(value, t.Mapping):
        items = t.cast("t.Mapping[object, object]", value).values()
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = t.cast("t.Iterable[object]", value)
    else:
        return
    for item in items:
        _check_aware_in(item)


def build_query(existing: str, pairs: Pairs) -> str:
    """Merge a path's query string with more pairs, encoded and sorted by key like Go's
    url.Values.Encode. Values of one key keep their order."""
    merged: dict[str, list[str]] = {}
    if existing:
        for part in existing.split("&"):
            if not part:
                continue
            key, _, val = part.partition("=")
            merged.setdefault(unquote_plus(key), []).append(unquote_plus(val))
    for key, value in pairs:
        values = encode_value(value)
        if values:
            merged.setdefault(key, []).extend(values)
    return urlencode([(k, v) for k in sorted(merged) for v in merged[k]])


def build_headers(pairs: Pairs) -> list[tuple[str, str]]:
    """Encode header pairs. Several values of one header are joined with ","."""
    out: list[tuple[str, str]] = []
    for key, value in pairs:
        values = encode_value(value)
        if not values:
            continue
        text = ",".join(values)
        check_header(key, text)
        out.append((key, text))
    return out


def check_header(name: str, value: str) -> None:
    """Refuse a header that would inject other headers, or that httpx cannot send."""
    if not name or not name.isascii() or any(c in name for c in "\r\n\0: "):
        raise InvalidRequestError(f"header name {name!r} is not valid")
    if any(c in value for c in "\r\n\0"):
        raise InvalidRequestError(f"header {name}: the value has a line break or a NUL")
    # httpx encodes header values as ASCII: any other character fails when the request is
    # sent. Refuse it here, as an OvhError.
    if not value.isascii():
        raise InvalidRequestError(f"header {name}: the value is not ASCII")


def to_jsonable(value: object) -> object:
    """Turn a request body into JSON data.

    A model gives the fields that were set, by their wire names: a field never set is not
    sent, and a field set to None is sent as null. A dict is sent as it is, with its
    NOT_GIVEN values left out. A datetime with no time zone is refused, at any depth.
    """
    if isinstance(value, pydantic.BaseModel):
        # pydantic sends a naive datetime with no offset: refuse it, as below.
        _check_aware_in(value)
        # The same data as BaseModel.to_dict, for any pydantic model.
        return dump(value)
    if value is None or isinstance(value, (str, int, float)):
        return value
    if isinstance(value, enum.Enum):
        return to_jsonable(t.cast("object", value.value))
    if isinstance(value, datetime.datetime):
        _check_aware(value)
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, t.Mapping):
        items = t.cast("t.Mapping[object, object]", value).items()
        return {str(k): to_jsonable(v) for k, v in items if not isinstance(v, NotGiven)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in t.cast("t.Iterable[object]", value)]
    raise InvalidRequestError(f"cannot send a {type(value).__name__} as JSON")


def encode_body(body: object) -> bytes:
    """The JSON bytes of a request body."""
    return json.dumps(to_jsonable(body), separators=(",", ":"), ensure_ascii=False).encode()
