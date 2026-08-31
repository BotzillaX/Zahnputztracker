"""Generating the message text (spec 9).

The provider sits behind a small interface, so a second one can be added
without touching the flow that uses it. Nothing here invents a fallback
text: if the provider is silent, slow or empty, the caller is told and
the run ends (9.3).
"""

from .base import ComposerError, generate, providers
from .prompt import PLACEHOLDER_HELP, build

__all__ = ["ComposerError", "PLACEHOLDER_HELP", "build", "generate", "providers"]
