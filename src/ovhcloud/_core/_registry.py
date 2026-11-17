# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""The operation registry: every operation of the SDK, by name and by route.

Each generated section has a small ``_registry`` module with its operations. It holds no
models, so it is cheap to load. The registry loads them only when it needs them:

- ``lookup_operation("vrack.get_vrack")`` loads the vrack section's registry.
- ``match_operation``, ``operations`` and the client's policy on a raw call load every
  section's registry once.

Unlike Go, where only imported packages are known, every operation of the SDK is known.
"""

from __future__ import annotations

import dataclasses
import importlib
import re
import threading
import typing as t

__all__ = [
    "Operation",
    "lookup_operation",
    "match_operation",
    "operations",
    "register_operations",
]

# The package that holds the generated sections, relative to this one.
_API_PACKAGE = __name__.rsplit(".", 2)[0] + ".api"


@dataclasses.dataclass(frozen=True, slots=True)
class Operation:
    """One API operation: its name in the SDK, its route and the IAM actions it needs.

    The generated methods pass theirs with each request, so an ApiError names the operation,
    and the ``read_only`` and ``allowed_operations`` options can decide whether to send it.
    """

    #: The section and the method a caller uses: "vrack.get_vrack". For a list the API
    #: paginates by cursor, it is the iterator, the only method that calls it.
    name: str
    #: The route: "GET", "/v1/vrack/{serviceName}".
    method: str
    path: str
    #: The API's one-line summary of the operation.
    summary: str = ""
    #: The IAM actions the caller's policy must allow.
    iam_actions: tuple[str, ...] = ()
    #: True when the API deprecated the operation.
    deprecated: bool = False
    #: The X-Schemas-Version sent with the request: the /v2 contract the SDK was generated
    #: from. None for /v1 routes.
    schemas_version: str | None = None

    @property
    def read_only(self) -> bool:
        """True when the operation only reads: its method is GET or HEAD."""
        return is_read_only(self.method)

    def __str__(self) -> str:
        return f"{self.name} ({self.method} {self.path})"


def is_read_only(method: str) -> bool:
    """True for GET and HEAD."""
    return method.upper() in ("GET", "HEAD")


class _Registry:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.by_name: dict[str, Operation] = {}
        # Each HTTP method's operations, with their path split on "/".
        self.by_route: dict[str, list[tuple[list[str], Operation]]] = {}
        self.loaded_sections: set[str] = set()
        self.all_loaded = False
        # False in the core's own tests: they register their own operations, and must give
        # the same results with or without generated sections in the tree.
        self.load_generated = True


_registry = _Registry()


def register_operations(*ops: Operation) -> None:
    """Add operations to the registry. An operation registered again under the same name
    replaces the first."""
    with _registry.lock:
        for op in ops:
            old = _registry.by_name.get(op.name)
            if old is not None:
                routes = _registry.by_route.get(old.method, [])
                _registry.by_route[old.method] = [r for r in routes if r[1] is not old]
            _registry.by_name[op.name] = op
            _registry.by_route.setdefault(op.method, []).append((op.path.split("/"), op))


def _load_section(module: str) -> None:
    """Load the registry of one generated section. Unknown sections are ignored."""
    with _registry.lock:
        if module in _registry.loaded_sections or not _registry.load_generated:
            return
        _registry.loaded_sections.add(module)
        name = f"{_API_PACKAGE}.{module}._registry"
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as err:
            if not _is_missing(err, name):
                raise
            return
        ops: t.Iterable[Operation] = getattr(mod, "OPERATIONS", ())
        register_operations(*ops)


def _load_all() -> None:
    """Load the registry of every generated section, once."""
    with _registry.lock:
        if _registry.all_loaded or not _registry.load_generated:
            return
        _registry.all_loaded = True
        name = f"{_API_PACKAGE}._sections"
        try:
            sections = importlib.import_module(name)
        except ModuleNotFoundError as err:
            if not _is_missing(err, name):
                raise
            return  # no generated sections: a checkout of the core alone
        modules: t.Iterable[str] = getattr(sections, "SECTIONS", ())
        for module in modules:
            _load_section(module)


def _is_missing(err: ModuleNotFoundError, name: str) -> bool:
    """True when err says that name, or a package above it, does not exist. An import error
    inside an existing module is a bug, and is not hidden."""
    return err.name is not None and (name == err.name or name.startswith(err.name + "."))


def operations() -> list[Operation]:
    """Every operation of the SDK, sorted by name."""
    _load_all()
    with _registry.lock:
        return sorted(_registry.by_name.values(), key=lambda op: op.name)


def lookup_operation(name: str) -> Operation | None:
    """The operation of that name, "vrack.get_vrack", or None."""
    section, dot, _ = name.partition(".")
    if dot:
        _load_section(section)
    with _registry.lock:
        return _registry.by_name.get(name)


def match_operation(method: str, path: str) -> Operation | None:
    """The operation a request with that method and path calls, or None.

    ``GET /v1/vrack/pn-12345`` gives vrack.get_vrack. A route with fewer parameters wins
    over one with more: /v1/me/bill matches GET /v1/me/bill, not GET /v1/me/{id}. A query
    string is ignored.

    Unlike Go, a path in another form still finds its operation: "/1.0/me" (the python-ovh
    form) is read as "/v1/me", and a path without its version, "/me", is tried with /v1,
    then /v2. The client still refuses to send such a path, and its error names the version
    found here.
    """
    _load_all()
    route = path.split("?", 1)[0]
    if route == "/1.0" or route.startswith("/1.0/"):
        return _match(method, "/v1" + route[len("/1.0") :])
    if _VERSIONED.match(route):
        return _match(method, route)
    return _match(method, "/v1" + route) or _match(method, "/v2" + route)


# The API version a path starts with: "/v1/me", "/v2/iam/policy".
_VERSIONED = re.compile(r"/v[0-9]+(/|$)")


def _match(method: str, route: str) -> Operation | None:
    segments = route.split("/")
    best: Operation | None = None
    best_params = -1
    with _registry.lock:
        routes = list(_registry.by_route.get(method.upper(), ()))
    for route_segments, op in routes:
        params = _match_segments(route_segments, segments)
        if params is not None and (best is None or params < best_params):
            best, best_params = op, params
    return best


def _match_segments(route: list[str], path: list[str]) -> int | None:
    """Match a path against a route. A {name} segment matches any non-empty segment.
    Return the number of parameters used, or None."""
    if len(route) != len(path):
        return None
    params = 0
    for want, got in zip(route, path, strict=True):
        if want.startswith("{") and want.endswith("}"):
            if not got:
                return None
            params += 1
        elif want != got:
            return None
    return params


def reset_for_tests(*, generated: bool = True) -> None:
    """Empty the registry. Tests only. With generated=False, the registry never loads the
    generated sections: it holds only what the test registers."""
    with _registry.lock:
        _registry.by_name.clear()
        _registry.by_route.clear()
        _registry.loaded_sections.clear()
        _registry.all_loaded = False
        _registry.load_generated = generated
