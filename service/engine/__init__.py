"""State detection and the execution of action chains (spec 2.6 to 2.8).

Nothing in this package knows anything about a concrete page. It reads
states and actions from the registry, asks the resolver whether a role is
visible, and carries out what the user has defined. Where it cannot
decide without guessing it stops and says so.
"""

from .approval import gate
from .runner import EngineStop, run_chain, run_once, state_report
from .states import detect
from .variables import space

__all__ = [
    "EngineStop",
    "detect",
    "gate",
    "run_chain",
    "run_once",
    "space",
    "state_report",
]
