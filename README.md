# Academic Writing Coach

A Codex skill for Indonesian and English academic writing. It supports large journal corpora, exact and bibliographic duplicate review, resumable extraction, evidence-grounded screening, critical synthesis, OCR-assisted PDF review, and end-to-end assignment drafting.

## Install

Copy this repository to the Codex skills directory as `academic-writing-coach`, then invoke `$academic-writing-coach` or let Codex select it automatically.

## Main resources

- `SKILL.md`: routing, academic integrity, critical analysis, writing, and delivery rules.
- `references/corpus-workflow.md`: large-corpus inventory, deduplication, screening, selection, and audit trail.
- `references/document-workflow.md`: PDF/Word reading and final-document verification.
- `scripts/corpus_inventory.py`: resumable inventory and duplicate candidates.
- `scripts/corpus_screen.py`: review ledger and verified selected-source export.
- `scripts/ocr_pdf.py`: OCR for scanned PDFs with Tesseract.js.
- `scripts/environment_check.py`: capability preflight.
- `scripts/self_test.py`: repeatable smoke/regression checks.

Run the self-test with the Python runtime used by Codex:

```powershell
python scripts/self_test.py
```

The skill preserves source files, records uncertainty and reading scope, and requires visual verification before a DOCX/PDF is described as ready for submission.
