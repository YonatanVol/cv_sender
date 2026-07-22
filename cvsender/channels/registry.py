"""Builds the channel adapters enabled for a run. Greenhouse is fully
implemented in this slice; Lever/Ashby/Comeet/LinkedIn/Email plug in here next.
"""
from __future__ import annotations

from .. import boards
from .greenhouse import GreenhouseChannel

IMPLEMENTED = {"greenhouse"}


def build_adapters(options: dict) -> dict:
    """channel name -> adapter, for the channels the run enabled + we implement."""
    enabled = set(options.get("channels", ["greenhouse"]))
    cfg = boards.load()
    out: dict = {}
    if "greenhouse" in enabled:
        out["greenhouse"] = GreenhouseChannel(cfg.get("greenhouse", []))
    return out
