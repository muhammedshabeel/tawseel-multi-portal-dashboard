from __future__ import annotations

"""Small runtime compatibility shim for Streamlit Cloud.

Some existing UI actions use ``icon="✅"`` with ``st.toast``. Newer
Streamlit versions reject shortcode-like/multi-character icon values and raise
``StreamlitAPIException`` after the underlying save has already succeeded.
This wrapper converts only the known invalid success tokens to a real emoji and
leaves every other toast call unchanged.
"""

try:
    import streamlit as _st

    _original_toast = _st.toast

    def _safe_toast(body, *, icon=None, duration="short"):
        if isinstance(icon, str) and icon.strip().upper() in {"OK", "SUCCESS"}:
            icon = "✅"
        return _original_toast(body, icon=icon, duration=duration)

    _st.toast = _safe_toast
except Exception:
    # Never prevent the application from starting because of this UI shim.
    pass
