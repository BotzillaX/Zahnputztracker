"""Everything the user teaches the application about the page.

Nothing in this package contains knowledge about a concrete page. It
contains the shape that knowledge takes, and the way it is stored.
"""

from .model import (  # noqa: F401
    KIND_LABELS,
    KINDS,
    MANY,
    QUANTITIES,
    SCOPE_LABELS,
    SCOPES,
    SEARCH,
    SESSION,
    SINGLE,
    RegistryError,
)
from .resolve import UnknownState  # noqa: F401
