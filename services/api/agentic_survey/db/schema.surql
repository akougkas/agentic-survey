-- Canonical SurrealDB schema for the Agentic Survey runtime.
--
-- Every definition is guarded by IF NOT EXISTS so apply is idempotent.
-- Pre-1.0: there are no migrations. When the schema changes, drop the
-- database and re-apply. ``apply_schema`` is the only entry point.
--
-- Workflow:
--   docker compose -f infra/docker-compose.local.yml down -v
--   docker compose -f infra/docker-compose.local.yml up -d surrealdb
--   cd services/api && uv run python -m agentic_survey.db.schema

DEFINE TABLE IF NOT EXISTS campaign SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS title ON TABLE campaign TYPE string;
DEFINE FIELD IF NOT EXISTS source ON TABLE campaign TYPE string
    ASSERT $value IN ["blank","seed"];
DEFINE FIELD IF NOT EXISTS state ON TABLE campaign TYPE string
    ASSERT $value IN ["draft","designing","reviewing","live","monitoring","closing","archived"];
DEFINE FIELD IF NOT EXISTS min_n ON TABLE campaign TYPE int
    ASSERT $value >= 1 AND $value <= max_n;
DEFINE FIELD IF NOT EXISTS max_n ON TABLE campaign TYPE int
    ASSERT $value >= min_n;
DEFINE FIELD IF NOT EXISTS outline_status ON TABLE campaign TYPE string
    ASSERT $value IN ["collecting_brief","ready_for_review"];
DEFINE FIELD IF NOT EXISTS outline ON TABLE campaign FLEXIBLE TYPE object;
DEFINE FIELD IF NOT EXISTS agent_models ON TABLE campaign FLEXIBLE TYPE option<object>;
DEFINE FIELD IF NOT EXISTS outline.min_n ON TABLE campaign TYPE int
    ASSERT $value = min_n;
DEFINE FIELD IF NOT EXISTS outline.max_n ON TABLE campaign TYPE int
    ASSERT $value = max_n;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE campaign TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS updated_at ON TABLE campaign TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS archived_at ON TABLE campaign TYPE option<datetime>;

DEFINE TABLE IF NOT EXISTS model_catalog SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS catalog_id ON TABLE model_catalog TYPE string;
DEFINE FIELD IF NOT EXISTS role ON TABLE model_catalog TYPE string
    ASSERT $value IN ["chatter","scientist","validator","analyst","embedding","ingest"];
DEFINE FIELD IF NOT EXISTS endpoint ON TABLE model_catalog TYPE string
    ASSERT $value IN ["mini","dynamo"];
DEFINE FIELD IF NOT EXISTS model_id ON TABLE model_catalog TYPE string;
DEFINE FIELD IF NOT EXISTS label ON TABLE model_catalog TYPE string;
DEFINE FIELD IF NOT EXISTS notes ON TABLE model_catalog TYPE option<string>;
DEFINE FIELD IF NOT EXISTS enabled ON TABLE model_catalog TYPE bool DEFAULT true;
DEFINE FIELD IF NOT EXISTS is_default ON TABLE model_catalog TYPE bool DEFAULT false;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE model_catalog TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS updated_at ON TABLE model_catalog TYPE datetime DEFAULT time::now();
DEFINE INDEX IF NOT EXISTS model_catalog_id_role ON TABLE model_catalog COLUMNS catalog_id, role UNIQUE;
DEFINE INDEX IF NOT EXISTS model_catalog_role ON TABLE model_catalog COLUMNS role;

DEFINE TABLE IF NOT EXISTS outline_revision SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE outline_revision TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS source ON TABLE outline_revision TYPE string
    ASSERT $value IN ["blank","seed","designer","scientist_approval"];
DEFINE FIELD IF NOT EXISTS summary ON TABLE outline_revision TYPE string;
DEFINE FIELD IF NOT EXISTS changed_sections ON TABLE outline_revision TYPE array<string>;
DEFINE FIELD IF NOT EXISTS outline ON TABLE outline_revision FLEXIBLE TYPE object;
DEFINE FIELD IF NOT EXISTS decision_gate ON TABLE outline_revision FLEXIBLE TYPE option<object>;
DEFINE FIELD IF NOT EXISTS designer_turn ON TABLE outline_revision TYPE option<record<designer_turn>>;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE outline_revision TYPE datetime DEFAULT time::now();

DEFINE TABLE IF NOT EXISTS designer_session SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE designer_session TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS status ON TABLE designer_session TYPE string
    ASSERT $value IN ["idle","active","ready_for_review","locked"];
DEFINE FIELD IF NOT EXISTS created_at ON TABLE designer_session TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS updated_at ON TABLE designer_session TYPE datetime DEFAULT time::now();

DEFINE TABLE IF NOT EXISTS designer_turn SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS session ON TABLE designer_turn TYPE record<designer_session>;
DEFINE FIELD IF NOT EXISTS role ON TABLE designer_turn TYPE string
    ASSERT $value IN ["designer","scientist"];
DEFINE FIELD IF NOT EXISTS content ON TABLE designer_turn TYPE string;
DEFINE FIELD IF NOT EXISTS chip_selected ON TABLE designer_turn TYPE option<int>;
DEFINE FIELD IF NOT EXISTS brain_b_intent ON TABLE designer_turn FLEXIBLE TYPE option<object>;
DEFINE FIELD IF NOT EXISTS get_user_input ON TABLE designer_turn FLEXIBLE TYPE option<object>;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE designer_turn TYPE datetime DEFAULT time::now();

DEFINE TABLE IF NOT EXISTS invite SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE invite TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS token ON TABLE invite TYPE string;
DEFINE FIELD IF NOT EXISTS label ON TABLE invite TYPE string DEFAULT "";
DEFINE FIELD IF NOT EXISTS status ON TABLE invite TYPE string
    ASSERT $value IN ["active","used","revoked"];
DEFINE FIELD IF NOT EXISTS created_at ON TABLE invite TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS used_at ON TABLE invite TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS revoked_at ON TABLE invite TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS session ON TABLE invite TYPE option<record<interview_session>>;
DEFINE INDEX IF NOT EXISTS invite_token_unique ON TABLE invite COLUMNS token UNIQUE;

DEFINE TABLE IF NOT EXISTS interview_session SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE interview_session TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS invite ON TABLE interview_session TYPE option<record<invite>>;
DEFINE FIELD IF NOT EXISTS participant_token ON TABLE interview_session TYPE string;
DEFINE FIELD IF NOT EXISTS consent_mode ON TABLE interview_session TYPE string
    ASSERT $value IN ["anonymous","named"];
DEFINE FIELD IF NOT EXISTS identity_label ON TABLE interview_session TYPE string DEFAULT "";
DEFINE FIELD IF NOT EXISTS persona_snapshot ON TABLE interview_session FLEXIBLE TYPE object;
DEFINE FIELD IF NOT EXISTS pinned_endpoint ON TABLE interview_session TYPE string;
DEFINE FIELD IF NOT EXISTS outline_snapshot ON TABLE interview_session TYPE record<outline_revision>;
DEFINE FIELD IF NOT EXISTS status ON TABLE interview_session TYPE string
    ASSERT $value IN ["consented","active","paused","finished","abandoned"];
DEFINE FIELD IF NOT EXISTS started_at ON TABLE interview_session TYPE datetime;
DEFINE FIELD IF NOT EXISTS updated_at ON TABLE interview_session TYPE datetime;
DEFINE FIELD IF NOT EXISTS finished_at ON TABLE interview_session TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS close_reason ON TABLE interview_session TYPE option<string>;
DEFINE FIELD IF NOT EXISTS paused_reason ON TABLE interview_session TYPE option<string>;
DEFINE FIELD IF NOT EXISTS abandoned_reason ON TABLE interview_session TYPE option<string>;
DEFINE FIELD IF NOT EXISTS micro_form_answers ON TABLE interview_session FLEXIBLE TYPE object DEFAULT {};

DEFINE TABLE IF NOT EXISTS interview_turn SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS session ON TABLE interview_turn TYPE record<interview_session>;
DEFINE FIELD IF NOT EXISTS role ON TABLE interview_turn TYPE string
    ASSERT $value IN ["agent","participant"];
DEFINE FIELD IF NOT EXISTS content ON TABLE interview_turn TYPE string;
DEFINE FIELD IF NOT EXISTS index ON TABLE interview_turn TYPE int
    ASSERT $value >= 0;
DEFINE FIELD IF NOT EXISTS validation ON TABLE interview_turn FLEXIBLE TYPE option<object>;
DEFINE FIELD IF NOT EXISTS chip_selected ON TABLE interview_turn TYPE option<int>;
DEFINE FIELD IF NOT EXISTS brain_b_intent ON TABLE interview_turn FLEXIBLE TYPE option<object>;
DEFINE FIELD IF NOT EXISTS get_user_input ON TABLE interview_turn FLEXIBLE TYPE option<object>;
DEFINE FIELD IF NOT EXISTS retrieval_audit_id ON TABLE interview_turn TYPE option<record<retrieval_audit>>;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE interview_turn TYPE datetime;
DEFINE INDEX IF NOT EXISTS interview_turn_session_index ON TABLE interview_turn COLUMNS session, `index` UNIQUE;

DEFINE TABLE IF NOT EXISTS validator_result SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS turn ON TABLE validator_result TYPE record<interview_turn>;
DEFINE FIELD IF NOT EXISTS coverage_score ON TABLE validator_result TYPE float;
DEFINE FIELD IF NOT EXISTS quality_score ON TABLE validator_result TYPE float;
DEFINE FIELD IF NOT EXISTS follow_up_needed ON TABLE validator_result TYPE bool;
DEFINE FIELD IF NOT EXISTS follow_up_reason ON TABLE validator_result TYPE string;
DEFINE FIELD IF NOT EXISTS is_spam ON TABLE validator_result TYPE bool;
DEFINE FIELD IF NOT EXISTS extracted_concepts ON TABLE validator_result TYPE array<object>;
DEFINE FIELD IF NOT EXISTS extracted_relations ON TABLE validator_result TYPE array<object>;
DEFINE FIELD IF NOT EXISTS objective_tags ON TABLE validator_result TYPE array<string>;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE validator_result TYPE datetime;
DEFINE INDEX IF NOT EXISTS validator_result_turn_unique ON TABLE validator_result COLUMNS turn UNIQUE;

DEFINE TABLE IF NOT EXISTS interview_event SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS session ON TABLE interview_event TYPE record<interview_session>;
DEFINE FIELD IF NOT EXISTS event_name ON TABLE interview_event TYPE string;
DEFINE FIELD IF NOT EXISTS payload ON TABLE interview_event TYPE object;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE interview_event TYPE datetime DEFAULT time::now();
DEFINE INDEX IF NOT EXISTS interview_event_session_idx ON TABLE interview_event COLUMNS session, created_at;

DEFINE TABLE IF NOT EXISTS knowledge_source SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE knowledge_source TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS kind ON TABLE knowledge_source TYPE string
    ASSERT $value IN ["url","pdf","raw_text","searxng_suggestion","bundle_seed"];
DEFINE FIELD IF NOT EXISTS url ON TABLE knowledge_source TYPE option<string>;
DEFINE FIELD IF NOT EXISTS title ON TABLE knowledge_source TYPE string;
DEFINE FIELD IF NOT EXISTS hash ON TABLE knowledge_source TYPE string;
DEFINE FIELD IF NOT EXISTS status ON TABLE knowledge_source TYPE string
    ASSERT $value IN ["queued","fetching","extracting","chunking","embedding",
                      "pending_approval","approved","rejected","failed","retired"];
DEFINE FIELD IF NOT EXISTS approved_at ON TABLE knowledge_source TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS approved_by ON TABLE knowledge_source TYPE option<string>;
DEFINE FIELD IF NOT EXISTS rationale ON TABLE knowledge_source TYPE string DEFAULT "";
DEFINE FIELD IF NOT EXISTS error_detail ON TABLE knowledge_source TYPE option<string>;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE knowledge_source TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS updated_at ON TABLE knowledge_source TYPE datetime DEFAULT time::now();
DEFINE INDEX IF NOT EXISTS knowledge_source_campaign_hash ON TABLE knowledge_source COLUMNS campaign, hash UNIQUE;

DEFINE TABLE IF NOT EXISTS knowledge_chunk SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE knowledge_chunk TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS source ON TABLE knowledge_chunk TYPE record<knowledge_source>;
DEFINE FIELD IF NOT EXISTS content ON TABLE knowledge_chunk TYPE string;
DEFINE FIELD IF NOT EXISTS embedding ON TABLE knowledge_chunk TYPE array<float>;
DEFINE FIELD IF NOT EXISTS approved ON TABLE knowledge_chunk TYPE bool DEFAULT false;
DEFINE FIELD IF NOT EXISTS position ON TABLE knowledge_chunk TYPE int
    ASSERT $value >= 0;
DEFINE FIELD IF NOT EXISTS char_start ON TABLE knowledge_chunk TYPE int
    ASSERT $value >= 0;
DEFINE FIELD IF NOT EXISTS char_end ON TABLE knowledge_chunk TYPE int
    ASSERT $value >= char_start;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE knowledge_chunk TYPE datetime DEFAULT time::now();
DEFINE ANALYZER IF NOT EXISTS ascii_lower TOKENIZERS class FILTERS lowercase, ascii;
DEFINE INDEX IF NOT EXISTS knowledge_chunk_campaign_idx ON TABLE knowledge_chunk COLUMNS campaign;
DEFINE INDEX IF NOT EXISTS knowledge_chunk_campaign_embedding ON TABLE knowledge_chunk
    FIELDS embedding MTREE DIMENSION 768;
DEFINE INDEX IF NOT EXISTS knowledge_chunk_campaign_content ON TABLE knowledge_chunk
    FIELDS content SEARCH ANALYZER ascii_lower BM25;

DEFINE TABLE IF NOT EXISTS retrieval_audit SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE retrieval_audit TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS surface ON TABLE retrieval_audit TYPE string
    ASSERT $value IN ["designer","interviewer"];
DEFINE FIELD IF NOT EXISTS designer_turn ON TABLE retrieval_audit TYPE option<record<designer_turn>>;
DEFINE FIELD IF NOT EXISTS interview_turn ON TABLE retrieval_audit TYPE option<record<interview_turn>>;
DEFINE FIELD IF NOT EXISTS brain ON TABLE retrieval_audit TYPE string
    ASSERT $value IN ["B"];
DEFINE FIELD IF NOT EXISTS query ON TABLE retrieval_audit TYPE string;
DEFINE FIELD IF NOT EXISTS top_k ON TABLE retrieval_audit TYPE int
    ASSERT $value > 0;
DEFINE FIELD IF NOT EXISTS chunk_ids ON TABLE retrieval_audit TYPE array<record<knowledge_chunk>>;
DEFINE FIELD IF NOT EXISTS scores ON TABLE retrieval_audit TYPE array<float>;
DEFINE FIELD IF NOT EXISTS mode ON TABLE retrieval_audit TYPE string DEFAULT 'hybrid'
    ASSERT $value IN ['bm25', 'vector', 'hybrid'];
DEFINE FIELD IF NOT EXISTS cache_hit ON TABLE retrieval_audit TYPE bool DEFAULT false;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE retrieval_audit TYPE datetime DEFAULT time::now();

DEFINE TABLE IF NOT EXISTS concept SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE concept TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS label ON TABLE concept TYPE string;
DEFINE FIELD IF NOT EXISTS type ON TABLE concept TYPE string DEFAULT "";
DEFINE FIELD IF NOT EXISTS embedding ON TABLE concept TYPE array<float>;
DEFINE FIELD IF NOT EXISTS first_seen ON TABLE concept TYPE datetime;
DEFINE FIELD IF NOT EXISTS mention_count ON TABLE concept TYPE int
    ASSERT $value >= 0;
DEFINE INDEX IF NOT EXISTS concept_campaign_label ON TABLE concept COLUMNS campaign, label UNIQUE;
DEFINE INDEX IF NOT EXISTS concept_campaign_embedding ON TABLE concept FIELDS embedding MTREE DIMENSION 768;

DEFINE TABLE IF NOT EXISTS mentioned_with SCHEMAFULL TYPE RELATION FROM concept TO concept;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE mentioned_with TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS session ON TABLE mentioned_with TYPE record<interview_session>;
DEFINE FIELD IF NOT EXISTS turn ON TABLE mentioned_with TYPE record<interview_turn>;
DEFINE FIELD IF NOT EXISTS kind ON TABLE mentioned_with TYPE string
    ASSERT $value IN ["co_occurrence","explicit_relation"];
DEFINE FIELD IF NOT EXISTS confidence ON TABLE mentioned_with TYPE float;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE mentioned_with TYPE datetime DEFAULT time::now();

DEFINE TABLE IF NOT EXISTS contradicts SCHEMAFULL TYPE RELATION FROM concept TO concept;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE contradicts TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS session ON TABLE contradicts TYPE record<interview_session>;
DEFINE FIELD IF NOT EXISTS turn ON TABLE contradicts TYPE record<interview_turn>;
DEFINE FIELD IF NOT EXISTS confidence ON TABLE contradicts TYPE float;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE contradicts TYPE datetime DEFAULT time::now();

DEFINE TABLE IF NOT EXISTS campaign_export SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS campaign ON TABLE campaign_export TYPE record<campaign>;
DEFINE FIELD IF NOT EXISTS manifest ON TABLE campaign_export FLEXIBLE TYPE object;
DEFINE FIELD IF NOT EXISTS export_path ON TABLE campaign_export TYPE option<string>;
DEFINE FIELD IF NOT EXISTS created_at ON TABLE campaign_export TYPE datetime DEFAULT time::now();
