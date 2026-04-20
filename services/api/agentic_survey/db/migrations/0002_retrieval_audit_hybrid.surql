-- M4: hybrid retrieval audit columns. Existing rows default to mode='hybrid'
-- and cache_hit=false so the admin audit drawer renders cleanly against any
-- pre-migration rows without a backfill step.

DEFINE FIELD IF NOT EXISTS mode ON retrieval_audit TYPE string DEFAULT 'hybrid'
    ASSERT $value IN ['bm25', 'vector', 'hybrid'];
DEFINE FIELD IF NOT EXISTS cache_hit ON retrieval_audit TYPE bool DEFAULT false;
