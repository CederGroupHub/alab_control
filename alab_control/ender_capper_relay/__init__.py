"""Deprecated alias: use ``alab_control.capper`` instead."""

from __future__ import annotations

import warnings

from alab_control.capper import Capper, CapperState

warnings.warn(
    "alab_control.ender_capper_relay is renamed to alab_control.capper; "
    "import Capper from alab_control.capper",
    DeprecationWarning,
    stacklevel=2,
)

# Historical names kept for older scripts.
EnderCapperRelay = Capper
EnderCapperRelayState = CapperState

__all__ = [
    "Capper",
    "CapperState",
    "EnderCapperRelay",
    "EnderCapperRelayState",
]
