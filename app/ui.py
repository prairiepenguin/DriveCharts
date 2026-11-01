"""Layout helpers shared by the Streamlit pages."""

from __future__ import annotations

import streamlit as st

# Narrow enough that two cards fit a phone content area, and a desktop row holds several.
METRIC_WIDTH = 156


def metric_row(specs: list[tuple[str, str, str | None]], *, border: bool = False) -> None:
    """Equal metric cards that wrap onto extra rows instead of squeezing into one."""
    with st.container(horizontal=True, gap="small"):
        for label, value, help_text in specs:
            st.metric(
                label,
                value,
                help=help_text,
                border=border,
                width=METRIC_WIDTH,
                height="stretch",
            )
