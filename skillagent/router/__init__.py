"""Routing: prompt → validated mini-plan (CONTRACTS §11)."""

from __future__ import annotations

from skillagent.router.preprocess import build_user_request, leading_segment_hint
from skillagent.router.router import Router, RouteResult

__all__ = ["RouteResult", "Router", "build_user_request", "leading_segment_hint"]
