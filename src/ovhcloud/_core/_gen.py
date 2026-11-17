# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Everything the generated sections use from the core, in one module.

``deprecated`` is typing_extensions.deprecated. The templates call it with category=None:
type checkers and editors show the deprecation, and nothing warns at run time, since the
operation still works until the API removes it.

Generated code imports this module only (``from ..._core import _gen``), with relative
imports, so the package can be renamed without touching generated code. A name here is a
contract with the templates: rename it only together with them.
"""

from __future__ import annotations

from typing_extensions import deprecated

from ._client import AsyncClient, Client
from ._models import BaseModel, OpenFloatEnum, OpenIntEnum, OpenStrEnum, writable
from ._registry import Operation, register_operations
from ._section import AsyncSectionApi, SectionApi
from ._types import NOT_GIVEN, NotGiven

__all__ = [
    "NOT_GIVEN",
    "AsyncClient",
    "AsyncSectionApi",
    "BaseModel",
    "Client",
    "NotGiven",
    "OpenFloatEnum",
    "OpenIntEnum",
    "OpenStrEnum",
    "Operation",
    "SectionApi",
    "deprecated",
    "register_operations",
    "writable",
]
