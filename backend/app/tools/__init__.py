# app/tools/__init__.py
from .base import BaseArgs, EmptyArgs
from .calculators import (
    PriceDiffQuote,
    calc_bmi,
    calc_bmr,
    calc_energy,
    calc_hydration,
    calc_progression,
    compute_macros,
    price_diff,
)
from .registry import TOOLS, RunContext, Tool, dispatch, tool

# Import all tool domain modules so decorators register into TOOLS
from . import admin
from . import comms
from . import fitness
from . import membership
from . import nutrition
from . import schedule
from . import support
from . import trainer_info
from . import trainer_ops
from . import wellness

__all__ = [
    "TOOLS",
    "Tool",
    "RunContext",
    "dispatch",
    "tool",
    "BaseArgs",
    "EmptyArgs",
    "calc_bmr",
    "calc_energy",
    "calc_bmi",
    "calc_hydration",
    "compute_macros",
    "calc_progression",
    "price_diff",
    "PriceDiffQuote",
    "schedule",
    "membership",
    "fitness",
    "wellness",
    "nutrition",
    "trainer_info",
    "support",
    "comms",
    "trainer_ops",
    "admin",
]
