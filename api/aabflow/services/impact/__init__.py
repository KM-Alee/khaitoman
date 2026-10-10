"""Canonical SDG impact cards (F16, PRD §8.5, T7.5)."""

from aabflow.services.impact.cards import build_impact
from aabflow.services.impact.view import assemble, check_id

__all__ = ["assemble", "build_impact", "check_id"]
