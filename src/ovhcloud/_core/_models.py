# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""The base of generated models and enums, and the decoding of responses.

Two rules make the SDK hard to break by an API change:

- **Enums are open.** OVHcloud adds enum values often. A value the SDK does not know
  becomes a member of the enum all the same: ``State("new")`` works, equals ``"new"``, and
  is not in ``list(State)``.
- **A response that does not match its schema is never an error.** The SDK first validates
  the response. When validation fails (a required field is missing, a number comes as a
  string...), the SDK builds the objects without validation: fields keep what the API sent,
  missing fields are None. ``is_validated(obj)`` tells it. A body that is not JSON is an error
  (DecodeError).
"""

from __future__ import annotations

import enum
import json
import types
import typing as t

import pydantic

from ._debug import LOGGER
from ._errors import DecodeError, InvalidRequestError
from ._types import NotGiven

if t.TYPE_CHECKING:
    from ._registry import Operation

__all__ = [
    "BaseModel",
    "OpenFloatEnum",
    "OpenIntEnum",
    "OpenStrEnum",
    "decode",
    "decode_raw",
    "dump",
    "is_validated",
    "to_body",
    "writable",
]


class BaseModel(pydantic.BaseModel):
    """The base class of every generated model.

    - Attributes are snake_case. The JSON names are their aliases. Build a model with the
      snake_case names: ``Widget(service_name="x")``. The JSON name also works at run time,
      but type checkers do not know it.
    - A field you do not set is not sent. A field you set to None is sent as null.
    - Fields the SDK does not know yet are kept: read them in ``model_extra``.
    - ``to_dict()`` and ``to_json()`` give the object as the API writes it: API names, only
      the fields that were set. Use them to log or return a result. ``model_dump()`` gives
      snake_case names and None for every field that was not set.
    - ``repr()`` shows only the fields that were set, and the unknown ones.
    - A response that does not match its schema is still decoded, without validation. Then
      a required field can be None although its type says it cannot, and a field can hold
      what the API sent, of another type. ``ovhcloud.is_validated(obj)`` is False for such
      an object. Check it, or test the fields, before you trust their types.
    """

    model_config = pydantic.ConfigDict(
        extra="allow",
        validate_by_name=True,
        validate_by_alias=True,
        # Build the validators on first use, not at import: a section has hundreds of models.
        defer_build=True,
        protected_namespaces=(),
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    #: True when the SDK built this object without validation. See is_validated.
    _ovh_unvalidated: bool = pydantic.PrivateAttr(default=False)

    def to_dict(self) -> dict[str, t.Any]:
        """This object as JSON data, the way the API writes it: API names, and only the fields
        that were set (a field set to None gives null). Dates are ISO 8601 strings and enums
        their values. The unknown fields (model_extra) are in it too."""
        return dump(self)

    def to_json(self, *, indent: int | None = None) -> str:
        """This object as a JSON string. Same content as to_dict."""
        return json.dumps(dump(self), indent=indent, ensure_ascii=False)

    def __repr_args__(self) -> t.Iterable[tuple[str | None, t.Any]]:
        # Only the fields that were set, and the unknown ones (extras). A large model
        # otherwise prints dozens of field=None that the API never sent.
        fields_set = self.model_fields_set
        known = type(self).model_fields
        for name, value in super().__repr_args__():
            if name is None or name in fields_set or name not in known:
                yield name, value


def dump(value: pydantic.BaseModel) -> dict[str, t.Any]:
    """value as JSON data, by API names, with only the fields that were set.

    No warnings: an object decoded without validation keeps what the API sent, even when
    its type is not the field's. It is dumped as it came.
    """
    return value.model_dump(mode="json", by_alias=True, exclude_unset=True, warnings=False)


def is_validated(value: object) -> bool:
    """False when the SDK decoded value without validation, because the response did not
    match its schema. Then a required field can be None, and a field can hold what the API
    sent, of another type. Check it before you trust the types of a result::

        widget = client.widget.get_widget("w1")
        if not ovhcloud.is_validated(widget):
            log.warning("unexpected response: %s", widget.to_json())

    It looks at one object: a nested object built without validation makes its parent
    False too. For a list, check each item. Anything else (an object you built, a str, a
    dict...) is True.

    The Go SDK has no such check: its decoder never fails on a missing field, and gives the
    zero value.
    """
    if isinstance(value, BaseModel):
        return not value._ovh_unvalidated  # pyright: ignore[reportPrivateUsage]
    return True


def _pseudo_member(cls: type[enum.Enum], value: object, base: type) -> enum.Enum:
    """A member for a value the enum does not list. It is kept, so the same value always
    gives the same member."""
    found = cls._value2member_map_.get(value)
    if found is not None:
        return found
    new = t.cast("t.Callable[[type, object], enum.Enum]", base.__new__)
    member = new(cls, value)
    member._name_ = str(value)  # pyright: ignore[reportAttributeAccessIssue]
    member._value_ = value
    return cls._value2member_map_.setdefault(value, member)


class OpenStrEnum(enum.StrEnum):
    """A string enum that accepts any string. Unknown values become new members."""

    @classmethod
    def _missing_(cls, value: object) -> t.Any:
        if isinstance(value, str):
            return _pseudo_member(cls, value, str)
        return None


class OpenIntEnum(enum.IntEnum):
    """An integer enum that accepts any integer. Unknown values become new members."""

    @classmethod
    def _missing_(cls, value: object) -> t.Any:
        if isinstance(value, int) and not isinstance(value, bool):
            return _pseudo_member(cls, value, int)
        return None


class OpenFloatEnum(float, enum.Enum):
    """A number enum that accepts any number. Unknown values become new members."""

    @classmethod
    def _missing_(cls, value: object) -> t.Any:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _pseudo_member(cls, float(value), float)
        return None


_adapters: dict[object, pydantic.TypeAdapter[t.Any]] = {}


def _adapter(tp: object) -> pydantic.TypeAdapter[t.Any]:
    """A TypeAdapter per type, built on first use. A race builds two: harmless."""
    adapter = _adapters.get(tp)
    if adapter is None:
        adapter = pydantic.TypeAdapter(t.cast("t.Any", tp))
        _adapters[tp] = adapter
    return adapter


def decode(tp: object, body: bytes) -> t.Any:
    """Decode a JSON response body as tp.

    An empty body gives None. When tp is str and the body is not JSON, the body is the
    string: some v1 routes answer a bare, unquoted string.
    """
    if not body:
        return None
    try:
        data = json.loads(body)
    except ValueError as err:
        if tp is str:
            return body.decode("utf-8", "replace")
        raise DecodeError(f"the response is not JSON: {err}") from None
    return convert(tp, data)


def decode_raw(body: bytes) -> t.Any:
    """Decode a JSON body as plain data (dicts, lists...). An empty body gives None, and a
    body that is not JSON gives its text."""
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return body.decode("utf-8", "replace")


def convert(tp: object, data: object) -> t.Any:
    """Validate data as tp, or build it without validation when that fails."""
    if tp is None or tp is t.Any:
        return data
    try:
        return _adapter(tp).validate_python(data)
    except pydantic.ValidationError as err:
        # Only where and why, never the values: str(err) quotes the response data, which may
        # hold secrets. Response data is logged only with debug_bodies.
        where = [(e["loc"], e["type"]) for e in err.errors(include_input=False, include_url=False)]
        LOGGER.debug("response does not match its schema, decoded without validation: %s", where)
        return _lenient(tp, data)


def _lenient(tp: object, data: object) -> t.Any:
    """Build data as tp without failing. Parts that match are validated, the others are
    kept as the API sent them."""
    if tp is None or tp is t.Any or tp is object:
        return data
    origin = t.get_origin(tp)
    args = t.get_args(tp)
    if origin is t.Annotated:
        return _lenient(args[0], data)
    if origin is t.Union or origin is types.UnionType:
        if data is None and type(None) in args:
            return None
        members = [a for a in args if a is not type(None)]
        for member in members:
            try:
                return _adapter(member).validate_python(data)
            except pydantic.ValidationError:
                continue
        return _lenient(members[0], data) if members else data
    if origin in (list, t.Sequence, tuple, set) and isinstance(data, list):
        item = args[0] if args else t.Any
        return [_lenient(item, x) for x in t.cast("list[object]", data)]
    if origin in (dict, t.Mapping) and isinstance(data, dict):
        value = args[1] if len(args) == 2 else t.Any
        return {k: _lenient(value, v) for k, v in t.cast("dict[str, object]", data).items()}
    if isinstance(tp, type):
        if issubclass(tp, pydantic.BaseModel):
            if isinstance(data, dict):
                return _lenient_model(tp, t.cast("dict[str, object]", data))
            return data
        if issubclass(tp, enum.Enum):
            try:
                return tp(data)
            except ValueError:
                return data
    try:
        return _adapter(t.cast("object", tp)).validate_python(data)
    except pydantic.ValidationError:
        return data


def _lenient_model(cls: type[pydantic.BaseModel], data: dict[str, object]) -> pydantic.BaseModel:
    """data as cls, built without validation. Each field is validated on its own. The model
    is marked unvalidated (is_validated) when a required field is missing or a field does not
    match its type."""
    values: dict[str, object] = {}
    fields_set: set[str] = set()
    used: set[str] = set()
    unvalidated = False
    for name, info in cls.model_fields.items():
        wire = info.validation_alias if isinstance(info.validation_alias, str) else None
        wire = wire or info.alias or name
        if wire in data:
            key = wire
        elif name in data:
            key = name
        else:
            if info.is_required():
                values[name] = None
                unvalidated = True
            else:
                values[name] = info.get_default(call_default_factory=True)
            continue
        used.add(key)
        fields_set.add(name)
        try:
            values[name] = _adapter(info.annotation).validate_python(data[key])
        except pydantic.ValidationError:
            values[name] = _lenient(info.annotation, data[key])
            unvalidated = True
    model = cls.model_construct(_fields_set=fields_set, **values)
    extra = {k: v for k, v in data.items() if k not in used}
    if extra and model.__pydantic_extra__ is not None:
        model.__pydantic_extra__.update(extra)
    if unvalidated and isinstance(model, BaseModel):
        model._ovh_unvalidated = True  # pyright: ignore[reportPrivateUsage]
    return model


def to_body(op: Operation, tp: object, body: object) -> object:
    """The body of a generated method, as its type tp.

    The methods are typed to take a model, but nothing stops a dict at run time. A dict (or
    a list) is validated as tp and turned into it, so it is sent like the model would be:
    the snake_case names become the API names. A body that does not match tp is refused
    with InvalidRequestError, before anything is sent. Any other body (a model, NOT_GIVEN,
    None, a str...) is kept as it is. The raw calls (client.post...) send a dict as it is.
    In both cases, a NOT_GIVEN value in a dict is left out, at any depth.

    Go has no such step: its compiler refuses a body of the wrong type.
    """
    if tp is None or tp is t.Any or not isinstance(body, (dict, list, tuple)):
        return body
    try:
        return _adapter(tp).validate_python(_drop_not_given(t.cast("object", body)))
    except pydantic.ValidationError as err:
        # Where and why, never the values: the body may hold secrets.
        problems = "; ".join(
            f"{'.'.join(str(x) for x in e['loc']) or 'body'}: {e['msg']}"
            for e in err.errors(include_input=False, include_url=False)[:5]
        )
        name = tp.__name__ if isinstance(tp, type) else str(tp)
        raise InvalidRequestError(
            f"{op.name}: the body does not match {name}: {problems}."
            " Build it with the model: its fields are typed"
        ) from None


def _drop_not_given(data: object) -> object:
    """data without its NOT_GIVEN dict values, at any depth, as to_jsonable does.

    pydantic would keep NOT_GIVEN as a value, and the API would get the string "NOT_GIVEN".
    """
    if isinstance(data, dict):
        items = t.cast("dict[object, object]", data).items()
        return {k: _drop_not_given(v) for k, v in items if not isinstance(v, NotGiven)}
    if isinstance(data, (list, tuple)):
        return [_drop_not_given(v) for v in t.cast("t.Iterable[object]", data)]
    return data


_M = t.TypeVar("_M", bound=pydantic.BaseModel)


def writable(value: pydantic.BaseModel, form: type[_M]) -> _M:
    """value as form, its request form: a deep copy without the fields form does not have.

    Like the Go SDK's Writable, it copies through JSON. The fields the API sets (read-only)
    are not in form, so they are left out, at every depth. So are the fields the SDK does not
    know (model_extra): the SDK cannot tell whether the API accepts them. A field that was
    not set stays unset, so it is not sent.
    """
    return t.cast("_M", convert(form, _known(form, dump(value))))


def _known(tp: object, data: object) -> object:
    """data with only the keys tp knows, at every depth."""
    origin = t.get_origin(tp)
    args = t.get_args(tp)
    if origin is t.Annotated:
        return _known(args[0], data)
    if origin is t.Union or origin is types.UnionType:
        if data is None:
            return None
        members = [a for a in args if a is not type(None)]
        if len(members) == 1:
            return _known(members[0], data)
        models = [a for a in members if isinstance(a, type) and issubclass(a, pydantic.BaseModel)]
        # A union of several models: which one data is cannot be told here. Validation does.
        return _known(models[0], data) if len(models) == 1 else data
    if origin in (list, t.Sequence, tuple, set) and isinstance(data, list):
        item = args[0] if args else t.Any
        return [_known(item, x) for x in t.cast("list[object]", data)]
    if origin in (dict, t.Mapping) and isinstance(data, dict):
        value = args[1] if len(args) == 2 else t.Any
        return {k: _known(value, v) for k, v in t.cast("dict[str, object]", data).items()}
    if isinstance(tp, type) and issubclass(tp, pydantic.BaseModel) and isinstance(data, dict):
        if not tp.__pydantic_complete__:
            # Models are built on first use: annotations are strings until then.
            tp.model_rebuild()
        given = t.cast("dict[str, object]", data)
        out: dict[str, object] = {}
        for name, info in tp.model_fields.items():
            wire = info.validation_alias if isinstance(info.validation_alias, str) else None
            wire = wire or info.alias or name
            if wire in given:
                out[wire] = _known(info.annotation, given[wire])
        return out
    return data
