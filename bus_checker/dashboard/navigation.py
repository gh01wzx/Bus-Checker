"""Page registry, so pages can link to each other without importing the app module."""

from __future__ import annotations

from typing import Any

import streamlit as st

REGISTRY: dict[str, Any] = {}


def link(key: str, label: str, icon: str | None = None) -> None:
    page = REGISTRY.get(key)
    if page is not None:
        st.page_link(page, label=label, icon=icon)
