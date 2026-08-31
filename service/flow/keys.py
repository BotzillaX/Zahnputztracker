"""The identifier of one entry, derived from its address.

The result list gives links. To decide whether a link has been dealt with
before, it has to be reduced to something stable: the address itself
carries tracking parameters, ordering hints and session noise that differ
from view to view, so comparing whole addresses would offer the same
entry again and again.

The rule comes from the user, not from the code: the address template in
the settings holds one placeholder, and what stands in its place is the
identifier. That keeps every trace of the target address out of this
repository (spec 14) and makes the rule visible and changeable in one
field of the settings.

A link the template does not fit is not interpreted. It is counted and
reported, and the entry behind it is left alone. Guessing an identifier
would risk writing to the same entry twice, which is the one mistake this
application must not make.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

PLACEHOLDER = "{kennung}"
# What may stand in place of the placeholder: everything up to the next
# separator of an address.
_PART = r"([^/?#]+)"


def usable(template: str) -> bool:
    """Does the template carry exactly one placeholder."""
    return template.count(PLACEHOLDER) == 1


def pattern(template: str) -> Optional[re.Pattern]:
    """The template as an expression, or None if it cannot be used."""
    template = (template or "").strip()
    if not usable(template):
        return None
    before, after = template.split(PLACEHOLDER)
    # Anything the target site appends (query, fragment) is allowed to
    # follow, because it says nothing about which entry this is.
    body = re.escape(before) + _PART + re.escape(after)
    try:
        return re.compile("^" + body + r"(?:[?#].*)?$")
    except re.error:
        return None


def key_of(href: str, template: str, base: str = "") -> str:
    """The identifier behind one link, or an empty string."""
    if not href:
        return ""
    address = urljoin(base, href) if base else href
    rule = pattern(template)
    if rule is None:
        return ""
    found = rule.match(address)
    return found.group(1) if found else ""


def address_of(key: str, template: str) -> str:
    """The address of one entry, built from its identifier.

    The list link may carry parameters that belong to the list, not to
    the entry. The address built here is the same for the same entry, no
    matter which view it was found in.
    """
    if not key or not usable(template):
        return ""
    return template.replace(PLACEHOLDER, key)
