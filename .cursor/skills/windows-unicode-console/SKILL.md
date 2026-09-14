---
name: windows-unicode-console
description: >-
  Prevents Windows UnicodeEncodeError (charmap codec) when running Python
  or scripts that print Unicode such as arrows (→), subscripts (₀), or
  German umlauts. Use on Windows before any native shell Python invocation
  (including pytest), when UnicodeEncodeError or charmap_encode appears, or
  when output contains →.
---

# Windows Unicode Console (charmap fix)

## Problem

On Windows PowerShell, Python stdout often uses the **cp1252/charmap** codec. Printing or logging strings with characters outside that set — common in this repo (`→`, `₀`, `₁`, `₂`, umlauts) — raises:

```text
UnicodeEncodeError: 'charmap' codec can't encode character '\u2192' ...
```

**Do not** strip Unicode from UI labels, user docs, or domain strings to fix this. Fix the **console encoding** instead.

## Agent rule: every Python shell command on Windows

Before **any** `.venv\Scripts\python.exe` invocation in the Shell tool, set UTF-8 for that command.

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m pytest tests/ -q --tb=short
```

Apply the same prefix for scripts, one-liners, and pre-commit-style runs:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m scripts.run_backtesting --help
```

| Variable | Purpose |
|----------|---------|
| `PYTHONIOENCODING=utf-8` | Forces stdin/stdout/stderr to UTF-8 |
| `PYTHONUTF8=1` | Enables Python UTF-8 mode (Python 3.12+ in this project) |

Use `working_directory` for the project root; do **not** use `&&` (PowerShell 5.x).

## If UnicodeEncodeError already occurred

1. Re-run the **same command** with the env prefix above.
2. Do **not** edit source files to replace `→` with `->` unless the user explicitly asks for ASCII-only output.
3. If the error is in **new** CLI code you wrote, add the reconfigure block below at entry.

## New CLI scripts and `main()` entry points

At the top of `main()` (or before first `print`/`logging` to console), reuse the project pattern from `scripts/replay_debug_dump.py`:

```python
import sys

def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def main() -> int:
    _configure_console_utf8()
    ...
```

For modules run only via pytest, `tests/conftest.py` already calls `_configure_console_utf8()` at import time — shell env prefix is still recommended for non-pytest runs.

## Logging

If a script configures `logging.StreamHandler()` and Unicode errors persist even with env vars, set the handler encoding explicitly:

```python
handler = logging.StreamHandler(sys.stdout)
if hasattr(handler.stream, "reconfigure"):
    handler.stream.reconfigure(encoding="utf-8", errors="replace")
```

## Out of scope

- **Streamlit / Docker / Linux CI** — UTF-8 is default; no extra step.
- **File I/O** — already uses `encoding="utf-8"` in this project; charmap errors are almost always **console** encoding.
- **User docs and UI strings** — keep `→` and German text; do not ASCII-fy for Windows console convenience.

## Quick checklist

- [ ] Windows shell command includes `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1';`
- [ ] New standalone CLI script calls `_configure_console_utf8()` in `main()`
- [ ] On failure, re-run with env vars — do not patch Unicode out of production strings
