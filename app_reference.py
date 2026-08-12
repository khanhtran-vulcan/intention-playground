"""Lightweight Streamlit entrypoint: V1 Reference only.

Use this on macOS when the full Comparison Lab app (`app.py`) segfaults after
startup — that path eagerly imports pandas/sklearn/torch-related stacks.

Full lab: `make run-lab` → `app.py`
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from reference_runtime.debug_trace import checkpoint, install_crash_diagnostics

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
install_crash_diagnostics(where="app_reference.module_import")

import reference_ui  # noqa: E402  — after dotenv + diagnostics

checkpoint("app_reference.after_reference_ui_import")

st.set_page_config(
    page_title="Intention V1 Reference",
    page_icon="⇢",
    layout="wide",
    initial_sidebar_state="collapsed",
)
checkpoint("app_reference.after_set_page_config")
# Page chrome / CSS live in reference_ui.render() so app.py tab stays consistent.
checkpoint("app_reference.before_reference_ui_render")
reference_ui.render()
checkpoint("app_reference.after_reference_ui_render")
