-- M5: knowledge graph wiring. Carries:
--   1. concept.type: free-form string captured from Validator extraction
--      (e.g. "process", "tool", "challenge"). Defaults to "" so pre-M5
--      concept rows parse without a backfill.
--   2. mentioned_with.created_at / contradicts.created_at: enables
--      newest-first ordering in list_concept_neighborhood without
--      relying on Surreal record-id lexicography.

DEFINE FIELD IF NOT EXISTS type ON TABLE concept TYPE string DEFAULT "";

DEFINE FIELD IF NOT EXISTS created_at ON TABLE mentioned_with TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS created_at ON TABLE contradicts TYPE datetime DEFAULT time::now();
