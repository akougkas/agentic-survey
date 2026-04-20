"""Campaign RAG folder export (M6).

Mirrors SurrealDB state to ``./campaigns/{slug}/rag/`` as a greppable
audit artifact. The on-disk folder is write-only from the runtime's
perspective: no hot path reads from it, and scientist-initiated sync is
the only trigger. SurrealDB stays the source of truth.
"""

from agentic_survey.services.rag_export.writer import (
    slugify_campaign_title,
    sync_campaign_rag_folder,
)

__all__ = ["slugify_campaign_title", "sync_campaign_rag_folder"]
