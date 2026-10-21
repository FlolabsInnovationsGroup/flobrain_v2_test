# Manual checks

These scripts run against a live MongoDB (and, for `embeddings.py` and `hybrid_retrieval.py`, a local FAISS index with `faiss` and `sentence-transformers` installed). They execute when imported, so they must not be named `test*.py`: Django's test runner would import them.

Run one from `flobrain-core/backend/`, for example:

```bash
python -m memory.manual_checks.mongo_workflow
```
