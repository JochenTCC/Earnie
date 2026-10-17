---
name: streamlit-doc-links
description: >-
  Keep Streamlit chapter → GitHub docs deep-links in sync when page titles,
  nav sections, help text, or linked Markdown headings change. Use when editing
  ui/pages/**, ui/help_hint.py, ui/doc_links.py, ui/backtesting.py captions that
  mention docs, or headings in docs/user-manual/**, docs/ui/**,
  docs/konfiguration/**, docs/einrichtung/**, docs/referenz/** (or docs/workflow/**, docs/dev/**
  for Dev pages) that are targets of PAGE_DOCS / MANUAL_URL.
---

# Streamlit → docs deep-links

Canonical registry: [`ui/doc_links.py`](ui/doc_links.py).
UI wiring: [`ui/help_hint.py`](ui/help_hint.py) (`render_page_title_with_help(..., page_docs_key=...)`).
Handbook base URL: `MANUAL_URL` (also used by Info / About and cloud demo).

## When this skill applies

Run the checklist **before calling the change done** if you:

- Add / rename / remove a Streamlit nav page (`url_path` in `ui/navigation.py`)
- Change page title help text or chapter behavior that the handbook describes
- Move / rename headings in user docs that are linked from `PAGE_DOCS`
- Add a plain-text `docs/...` mention in UI captions (must become a clickable URL)

## Checklist

```
Streamlit doc links:
- [ ] PAGE_DOCS / NAV_DOC_PAGE_KEYS updated for every registered url_path
- [ ] page_docs_key= passed to render_page_title_with_help on that page
- [ ] Primary target is handbook section when one exists; else best docs/* chapter
- [ ] GitHub fragment still matches heading slug (or explicit <a id="…">)
- [ ] Secondary tech docs listed only when they help operators for that page
- [ ] Captions that mention docs use markdown_doc_link / docs_blob_url (no bare paths)
- [ ] Handbook / docs/* prose updated if chapter behavior changed
- [ ] tests/test_doc_links.py still green (registry ↔ nav coverage)
```

## Fragment rules

- Prefer GitHub auto-slugs from existing `##` / `###` headings.
- Add an explicit `<a id="stable-id"></a>` in the Markdown file only when the auto-slug is fragile (punctuation, long titles) — same pattern as `#gesamtkosten-jahres-verbrauch-kwh`.
- Do **not** invent backlog letter IDs for this maintenance work.

## Out of scope

- Serving docs inside Streamlit / MkDocs
- Linking every expander/subheader unless the user asks for a deeper pass
