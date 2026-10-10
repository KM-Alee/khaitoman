"""Onboarding service. The worker map loads ``process_job`` from this package."""

from .jobs import process_job

__all__ = ["process_job"]
