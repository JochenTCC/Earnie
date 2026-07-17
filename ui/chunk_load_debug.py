"""Temporary debug probe: Streamlit dynamic-import chunk failures (mobile Monitor)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import unquote

import streamlit as st

# #region agent log
_DEBUG_LOG = Path(__file__).resolve().parents[1] / "debug-5fee17.log"
_QP_KEY = "_dbg_chunk"
_SESSION_BASELINE = "_chunk_dbg_baseline_logged"


def _append_ndjson(payload: dict) -> None:
    payload.setdefault("sessionId", "5fee17")
    payload.setdefault("timestamp", int(time.time() * 1000))
    with _DEBUG_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def log_server_chunk_baseline() -> None:
    """Once per session: Streamlit version + TextInput/Selectbox chunk filenames."""
    if st.session_state.get(_SESSION_BASELINE):
        return
    st.session_state[_SESSION_BASELINE] = True
    try:
        import streamlit as st_mod

        js_dir = Path(st_mod.__file__).resolve().parent / "static" / "static" / "js"
        chunks = sorted(
            p.name
            for p in js_dir.iterdir()
            if p.suffix == ".js"
            and (
                p.name.startswith("TextInput.")
                or p.name.startswith("Selectbox.")
                or p.name.startswith("DateInput.")
            )
        )
        _append_ndjson(
            {
                "location": "ui/chunk_load_debug.py:baseline",
                "message": "server_chunk_baseline",
                "hypothesisId": "A",
                "data": {
                    "streamlit_version": st_mod.__version__,
                    "chunks": chunks,
                    "js_dir_exists": js_dir.is_dir(),
                },
            }
        )
    except Exception as exc:  # noqa: BLE001 — debug only
        _append_ndjson(
            {
                "location": "ui/chunk_load_debug.py:baseline",
                "message": "server_chunk_baseline_error",
                "hypothesisId": "A",
                "data": {"error": str(exc)},
            }
        )


def process_debug_query_params() -> None:
    """Ingest client chunk-failure report relayed via query param (works on phone)."""
    raw = st.query_params.get(_QP_KEY)
    if not raw:
        return
    try:
        data = json.loads(unquote(str(raw)))
    except Exception as exc:  # noqa: BLE001 — debug only
        data = {"parseError": str(exc), "rawHead": str(raw)[:180]}
    _append_ndjson(
        {
            "location": "ui/chunk_load_debug.py:query",
            "message": "client_chunk_report",
            "hypothesisId": str(data.get("hypothesisId") or "A-E"),
            "data": data,
        }
    )
    try:
        del st.query_params[_QP_KEY]
    except Exception:  # noqa: BLE001 — debug only
        pass
    st.sidebar.caption("chunk-debug: report logged")


def inject_chunk_load_probe() -> None:
    """Browser probe: catch dynamic-import failures, probe URL, relay to Python."""
    st.html(
        """
<script>
(function () {
  if (window.__earnieChunkDbg) return;
  window.__earnieChunkDbg = true;
  var ENDPOINT = 'http://127.0.0.1:7268/ingest/f9070e92-40dd-4c2d-a6c5-b16f523343eb';
  var SESSION = '5fee17';

  function postLocal(payload) {
    try {
      fetch(ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Debug-Session-Id': SESSION
        },
        body: JSON.stringify(Object.assign({
          sessionId: SESSION,
          timestamp: Date.now()
        }, payload))
      }).catch(function () {});
    } catch (e) {}
  }

  function relayToStreamlit(data) {
    try {
      if (sessionStorage.getItem('earnie_chunk_dbg_sent') === '1') return;
      sessionStorage.setItem('earnie_chunk_dbg_sent', '1');
      var u = new URL(window.location.href);
      u.searchParams.set('_dbg_chunk', encodeURIComponent(JSON.stringify(data)));
      window.location.replace(u.toString());
    } catch (e) {}
  }

  function probeUrl(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      return r.text().then(function (text) {
        return {
          status: r.status,
          contentType: r.headers.get('content-type'),
          bodyLen: text.length,
          bodyHead: text.slice(0, 60),
          urlLen: url.length,
          urlEndsWithJs: /\\.js(\\?|$)/i.test(url)
        };
      });
    }).catch(function (e) {
      return { fetchError: String(e) };
    });
  }

  function classify(probe) {
    if (!probe) return 'E';
    if (probe.fetchError) return 'D';
    if (probe.status === 404) return 'A';
    if (probe.status === 429) return 'B';
    if (probe.status >= 400) return 'B';
    if (probe.contentType && probe.contentType.indexOf('javascript') < 0
        && probe.contentType.indexOf('ecmascript') < 0) return 'C';
    if (probe.bodyHead && probe.bodyHead.trim().charAt(0) === '<') return 'C';
    if (probe.urlEndsWithJs === false) return 'D';
    return 'E';
  }

  function handle(msg) {
    var m = String(msg || '');
    var match = m.match(/https?:\\/\\/[^\\s)'\"]+/);
    var url = match ? match[0] : null;
    var base = {
      message: m.slice(0, 400),
      failedUrl: url,
      ua: navigator.userAgent,
      viewportW: window.innerWidth,
      viewportH: window.innerHeight,
      href: location.href
    };
    postLocal({
      location: 'chunk_load_debug.js:catch',
      message: 'chunk_load_failure_seen',
      hypothesisId: 'A-E',
      data: base
    });
    if (!url) {
      base.hypothesisId = 'E';
      relayToStreamlit(base);
      return;
    }
    probeUrl(url).then(function (probe) {
      base.probe = probe;
      base.hypothesisId = classify(probe);
      postLocal({
        location: 'chunk_load_debug.js:probe',
        message: 'chunk_url_probed',
        hypothesisId: base.hypothesisId,
        data: base
      });
      relayToStreamlit(base);
    });
  }

  window.addEventListener('unhandledrejection', function (ev) {
    var reason = ev && ev.reason;
    var msg = reason && (reason.message || String(reason));
    if (msg && msg.indexOf('Failed to fetch dynamically imported module') >= 0) {
      handle(msg);
    }
  });

  window.addEventListener('error', function (ev) {
    var msg = (ev && ev.message) || '';
    if (msg.indexOf('Failed to fetch dynamically imported module') >= 0
        || msg.indexOf('Loading chunk') >= 0
        || msg.indexOf('ChunkLoadError') >= 0) {
      handle(msg);
    }
  });

  postLocal({
    location: 'chunk_load_debug.js:ready',
    message: 'chunk_probe_injected',
    hypothesisId: 'E',
    data: {
      ua: navigator.userAgent,
      viewportW: window.innerWidth,
      href: location.href
    }
  });
})();
</script>
        """,
        unsafe_allow_javascript=True,
    )


def install_chunk_load_debug() -> None:
    """Call once per Streamlit run from app.main()."""
    process_debug_query_params()
    log_server_chunk_baseline()
    inject_chunk_load_probe()
# #endregion
