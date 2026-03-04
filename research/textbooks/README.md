# Research Textbooks Workspace

Drop textbook PDFs into this folder for ingestion.

- Raw PDFs: `research/textbooks/*.pdf`
- Generated sidecars: `research/textbooks/ingested/*.md`

Run:

```bash
python -m handlers.research.science_ingest
```

Ingestion is idempotent by file hash and sidecar presence.
