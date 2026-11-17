# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""The NOT_GIVEN sentinel.

Optional arguments default to NOT_GIVEN. It means "not set": the SDK sends nothing for it.
None means the same for query and header parameters, which cannot carry a null.
"""

from __future__ import annotations

import enum
import typing as t

__all__ = ["NOT_GIVEN", "NotGiven", "NotGivenOr"]


class NotGiven(enum.Enum):
    """The type of NOT_GIVEN. It has one member, so type checkers can narrow it."""

    NOT_GIVEN = "NOT_GIVEN"

    def __bool__(self) -> t.Literal[False]:
        return False

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN: t.Final = NotGiven.NOT_GIVEN
"""The value of an optional argument the caller did not set."""

_T = t.TypeVar("_T")

NotGivenOr = t.Union[_T, NotGiven]  # noqa: UP007 (a generic alias needs Union on 3.11)
"""``NotGivenOr[str]`` is ``str | NotGiven``."""
