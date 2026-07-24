"""Builds the channel adapters enabled for a run. LinkedIn/Email plug in next."""
from __future__ import annotations

from .. import boards
from .ashby import AshbyChannel
from .comeet import ComeetChannel
from .greenhouse import GreenhouseChannel
from .lever import LeverChannel

BUILDERS = {
    "greenhouse": GreenhouseChannel,
    "lever": LeverChannel,
    "ashby": AshbyChannel,
    "comeet": ComeetChannel,
}
IMPLEMENTED = set(BUILDERS)


def build_adapters(options: dict) -> dict:
    """channel name -> adapter, for the channels the run enabled + we implement."""
    enabled = set(options.get("channels", ["greenhouse"]))
    cfg = boards.load()
    out: dict = {}
    for name, builder in BUILDERS.items():
        if name in enabled:
            out[name] = builder(cfg.get(name, []))
    return out
