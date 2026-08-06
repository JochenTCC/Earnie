---
name: doc-review-findings
description: >-
  Correct open items under ## Document Review Findings in
  backlog/Backlog-Bugfixes.md (user docs under docs/**, README, renames,
  merges, abbreviation lists), then archive them in backlog/Backlog-Erledigt.md.
  Use when the user asks to fix document review findings, process Doc Review
  Findings, clear that chapter, or correct issues listed after a docs review.
---

# Document Review Findings

Source chapter: `## Document Review Findings` in [`backlog/Backlog-Bugfixes.md`](backlog/Backlog-Bugfixes.md).  
Checklist context (optional): [`backlog/Doc-Review-Checklist.md`](backlog/Doc-Review-Checklist.md).

Unlike code bugfixes, these items **skip** `## Bugfix Verifications Pending` — after the doc change is done, move straight to [`backlog/Backlog-Erledigt.md`](backlog/Backlog-Erledigt.md).

## When this skill applies

- User points at `## Document Review Findings` or asks to process / fix those items
- User mentions “document review findings”, “doc review corrections”, or similar
- Agent is about to edit user docs solely to clear a finding from that chapter

## Workflow

Copy and track:

```
Doc review finding:
- [ ] 1. Read the finding (and nested bullets) fully; ask if scope is unclear
- [ ] 2. Locate target docs / links / TOC entries
- [ ] 3. Apply the correction (German user docs — see german-user-docs.mdc)
- [ ] 4. Update cross-links, docs/README.md TOC, and Streamlit deep-links if paths/titles changed (streamlit-doc-links skill)
- [ ] 5. Remove the finding from Backlog-Bugfixes.md (keep the empty chapter heading)
- [ ] 6. Archive in Backlog-Erledigt.md as ### Document Review … (YYYY-MM-DD) with - [x]
```

### Step details

1. **Scope** — One finding (top-level `- [ ]`) per pass unless the user asks for a batch. Nested bullets are part of the same finding. Ask before inventing content the finding does not specify (e.g. full abbreviation glossary wording).

2. **User docs** — Paths under `docs/user-manual/`, `docs/einrichtung/`, `docs/konfiguration/`, `docs/ui/`, `docs/referenz/`, and `docs/README.md` stay **German**. Keep identifiers, paths, and env vars verbatim.

3. **Renames / merges** — Update all inbound links (TOC, handbook, other chapters, `ui/doc_links.py` / PAGE_DOCS if applicable). Prefer one joint document when the finding says “merge”; do not leave a stub unless the user asks.

4. **Archive format** (Europe/Vienna date):

```markdown
### Document Review <short topic> (YYYY-MM-DD)

- [x] <original finding text, adapted if the fix renamed paths>
```

5. **Do not**
   - Move findings into `## Bugfix Verifications Pending`
   - Strikethrough items in `Backlog-Bugfixes.md`
   - Remove the `## Document Review Findings` chapter heading when empty
   - Bump `version.py` for docs-only corrections (unless the user explicitly asks)

## Related

- Lifecycle summary: [`.cursor/rules/backlog.mdc`](../../rules/backlog.mdc)
- Deep-links after rename/heading change: [streamlit-doc-links](../streamlit-doc-links/SKILL.md)
