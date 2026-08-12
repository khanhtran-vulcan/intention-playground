"""Intention V1 Reference Runtime.

Independent reference implementation of the BE V1 Intention Detection & Routing
architecture (Policy Gate -> Tier 0 -> Classifier -> Validator -> Outcome).

Deliberately decoupled from `core` and `routers` (the Comparison Lab): no shared
base classes, no shared state. See docs/reference-runtime.md for the full design
and its documented divergences from the BE source-of-truth document.
"""

from __future__ import annotations
