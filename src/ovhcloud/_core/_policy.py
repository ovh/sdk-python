# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""What a client may send: read-only mode and the allow-list of operations.

Both are checked before a token is fetched or a byte is sent.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import typing as t

from ._errors import ConfigurationError, NotAllowedError
from ._registry import Operation, is_read_only

__all__ = ["Policy"]


@dataclasses.dataclass(frozen=True, slots=True)
class Policy:
    """The client's policy. Empty: everything may be sent."""

    read_only: bool = False
    #: Operations allowed in read-only mode all the same, as name patterns.
    read_only_except: tuple[str, ...] = ()
    #: When not None, only operations whose name matches one of these patterns are sent.
    allowed: tuple[str, ...] | None = None

    @classmethod
    def build(
        cls,
        read_only: bool | t.Iterable[str],
        allowed_operations: t.Iterable[str] | None,
    ) -> Policy:
        """Check the client options and return the policy.

        ``read_only`` is True, False, or the patterns of operations allowed all the same.
        """
        except_: tuple[str, ...] = ()
        if read_only is not True and read_only is not False:
            if isinstance(read_only, str):
                read_only = (read_only,)
            except_ = tuple(read_only)
            _check_patterns("read_only", except_)
            read_only = True
        allowed: tuple[str, ...] | None = None
        if allowed_operations is not None:
            if isinstance(allowed_operations, str):
                allowed_operations = (allowed_operations,)
            allowed = tuple(allowed_operations)
            if not allowed:
                raise ConfigurationError("allowed_operations: no pattern: nothing could be sent")
            _check_patterns("allowed_operations", allowed)
        return cls(read_only=read_only, read_only_except=except_, allowed=allowed)

    @property
    def active(self) -> bool:
        return self.read_only or self.allowed is not None

    def check(self, op: Operation | None, method: str, path: str) -> None:
        """Raise NotAllowedError when the policy refuses the request. op is None when the
        registry does not know the route."""
        if not self.active:
            return
        name = op.name if op is not None else ""

        def refuse(reason: str) -> NotAllowedError:
            return NotAllowedError(operation=name, method=method, path=path, reason=reason)

        if (
            self.read_only
            and not is_read_only(method)
            and (not name or not _match_any(self.read_only_except, name))
        ):
            raise refuse("the client is read-only (read_only=True)")
        if self.allowed is not None:
            if not name:
                raise refuse(
                    "the client only sends listed operations (allowed_operations), "
                    "and no section of the SDK declares this route"
                )
            if not _match_any(self.allowed, name):
                raise refuse("not in the operations the client may send (allowed_operations)")


def _check_patterns(option: str, patterns: t.Iterable[str]) -> None:
    for p in patterns:
        if not isinstance(p, str) or not p.strip():  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ConfigurationError(f"{option}: an empty pattern")
        if p.count("[") != p.count("]"):
            raise ConfigurationError(f"{option}: pattern {p!r}: unbalanced brackets")


def _match_any(patterns: t.Iterable[str], name: str) -> bool:
    """Match a name against glob patterns: "vrack.*", "*.get_*". Case-sensitive."""
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)
