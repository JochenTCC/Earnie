"""Recover from stale Streamlit JS chunks after container/Streamlit upgrades."""
from __future__ import annotations

import streamlit as st


def inject_chunk_load_recovery() -> None:
    """
    Once per tab: hard-reload if a dynamic import fails (old hashed /static/js chunk).

    After a Streamlit upgrade, a phone may keep an old main bundle that imports
    chunk names that no longer exist; the server then returns index.html for those
    URLs and the UI shows TypeError: Failed to fetch dynamically imported module.
    """
    st.html(
        """
<script>
(function () {
  if (window.__earnieChunkRecovery) return;
  window.__earnieChunkRecovery = true;

  function isChunkLoadFailure(msg) {
    msg = String(msg || '');
    return msg.indexOf('Failed to fetch dynamically imported module') >= 0
      || msg.indexOf('Loading chunk') >= 0
      || msg.indexOf('ChunkLoadError') >= 0;
  }

  function reloadOnce() {
    try {
      if (sessionStorage.getItem('earnie_chunk_reloaded') === '1') return;
      sessionStorage.setItem('earnie_chunk_reloaded', '1');
      var u = new URL(window.location.href);
      u.searchParams.set('_earnie_cb', String(Date.now()));
      window.location.replace(u.toString());
    } catch (e) {
      window.location.reload();
    }
  }

  window.addEventListener('unhandledrejection', function (ev) {
    var reason = ev && ev.reason;
    var msg = reason && (reason.message || String(reason));
    if (isChunkLoadFailure(msg)) reloadOnce();
  });

  window.addEventListener('error', function (ev) {
    if (isChunkLoadFailure(ev && ev.message)) reloadOnce();
  });
})();
</script>
        """,
        unsafe_allow_javascript=True,
    )
