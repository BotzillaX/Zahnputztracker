"""Signing in and contacting one entry (spec 7 and 8).

The steps live here, the page knowledge lives in the registry. What the
code expects of the registry is listed in contract.py and nowhere else.

The submodules are exported, not the functions inside them: a name like
``contact`` exists both as a module and as a function, and shadowing the
module would make ``from ..flow import contact`` mean two different
things depending on the import order.
"""

from . import contact, contract, login, manager
from .manager import manager as jobs

__all__ = ["contact", "contract", "jobs", "login", "manager"]
