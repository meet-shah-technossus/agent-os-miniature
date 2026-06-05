"""Orchestrator API routes - backward-compatible facade.

This module re-exports the combined router from the split route files
(pipeline.py, gates.py, history.py) so existing imports continue to work.
"""
from __future__ import annotations

from fastapi import APIRouter

from .pipeline import router as _pipeline_router
from .gates import router as _gates_router
from .history import router as _history_router

# Combine all three into a single router for backward-compat imports
router = APIRouter()
router.include_router(_pipeline_router)
router.include_router(_gates_router)
router.include_router(_history_router)
