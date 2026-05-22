BEGIN;

CREATE SCHEMA IF NOT EXISTS capture;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE OR REPLACE FUNCTION capture.normalize_entity_name(input text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT NULLIF(
    trim(regexp_replace(lower(unaccent(coalesce(input, ''))), '[^a-z0-9]+', ' ', 'g')),
    ''
  );
$$;

CREATE OR REPLACE FUNCTION capture.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS capture.entities (
  entity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_uei varchar(12),
  cage_code varchar(5),
  legal_name text NOT NULL CHECK (length(trim(legal_name)) > 0),
  normalized_legal_name text GENERATED ALWAYS AS (capture.normalize_entity_name(legal_name)) STORED,
  alias_names text[] NOT NULL DEFAULT '{}'::text[],
  parent_entity_id uuid REFERENCES capture.entities(entity_id) ON DELETE SET NULL,
  is_excluded boolean NOT NULL DEFAULT false,
  exclusion_checked_at timestamptz,
  exclusion_details jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_system text NOT NULL DEFAULT 'SAM.gov',
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (canonical_uei IS NULL OR (canonical_uei = upper(canonical_uei) AND canonical_uei ~ '^[A-Z0-9]{12}$')),
  CHECK (cage_code IS NULL OR (cage_code = upper(cage_code) AND cage_code ~ '^[A-Z0-9]{5}$'))
);

CREATE UNIQUE INDEX IF NOT EXISTS entities_canonical_uei_uq
  ON capture.entities (canonical_uei)
  WHERE canonical_uei IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS entities_cage_code_uq
  ON capture.entities (cage_code)
  WHERE cage_code IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS entities_normalized_legal_name_uq
  ON capture.entities (normalized_legal_name);

CREATE INDEX IF NOT EXISTS entities_parent_entity_idx
  ON capture.entities (parent_entity_id);

CREATE INDEX IF NOT EXISTS entities_alias_names_gin_idx
  ON capture.entities USING gin (alias_names);

CREATE INDEX IF NOT EXISTS entities_legal_name_trgm_idx
  ON capture.entities USING gin (legal_name gin_trgm_ops);

DROP TRIGGER IF EXISTS entities_touch_updated_at ON capture.entities;
CREATE TRIGGER entities_touch_updated_at
BEFORE UPDATE ON capture.entities
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.opportunities (
  opportunity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  notice_id text NOT NULL,
  solicitation_number text,
  title text NOT NULL,
  opportunity_type text,
  base_type text,
  active_status text NOT NULL DEFAULT 'unknown',
  posted_at timestamptz,
  response_deadline timestamptz,
  archive_at timestamptz,
  naics_code varchar(6),
  psc_code varchar(4),
  set_aside_code text,
  set_aside_description text,
  funding_agency_name text,
  funding_agency_code text,
  subtier_name text,
  office_name text,
  full_parent_path_name text,
  full_parent_path_code text,
  organization_type text,
  place_of_performance jsonb NOT NULL DEFAULT '{}'::jsonb,
  office_address jsonb NOT NULL DEFAULT '{}'::jsonb,
  estimated_value_min numeric(18,2),
  estimated_value_max numeric(18,2),
  currency_code char(3) NOT NULL DEFAULT 'USD',
  description_url text,
  ui_link text,
  resource_links text[] NOT NULL DEFAULT '{}'::text[],
  sow_text text,
  sow_embedding vector(1536),
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  search_tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', coalesce(title, '') || ' ' || coalesce(sow_text, ''))
  ) STORED,
  CONSTRAINT opportunities_notice_id_uq UNIQUE (notice_id),
  CHECK (naics_code IS NULL OR naics_code ~ '^[0-9]{2,6}$'),
  CHECK (psc_code IS NULL OR length(psc_code) BETWEEN 1 AND 4),
  CHECK (estimated_value_min IS NULL OR estimated_value_min >= 0),
  CHECK (estimated_value_max IS NULL OR estimated_value_max >= 0),
  CHECK (
    estimated_value_min IS NULL
    OR estimated_value_max IS NULL
    OR estimated_value_min <= estimated_value_max
  )
);

CREATE INDEX IF NOT EXISTS opportunities_solicitation_number_idx
  ON capture.opportunities (solicitation_number);

CREATE INDEX IF NOT EXISTS opportunities_posted_at_idx
  ON capture.opportunities (posted_at DESC);

CREATE INDEX IF NOT EXISTS opportunities_response_deadline_idx
  ON capture.opportunities (response_deadline);

CREATE INDEX IF NOT EXISTS opportunities_naics_psc_idx
  ON capture.opportunities (naics_code, psc_code);

CREATE INDEX IF NOT EXISTS opportunities_agency_idx
  ON capture.opportunities (funding_agency_code, funding_agency_name);

CREATE INDEX IF NOT EXISTS opportunities_set_aside_idx
  ON capture.opportunities (set_aside_code);

CREATE INDEX IF NOT EXISTS opportunities_search_tsv_idx
  ON capture.opportunities USING gin (search_tsv);

CREATE INDEX IF NOT EXISTS opportunities_sow_embedding_hnsw_idx
  ON capture.opportunities
  USING hnsw (sow_embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 96)
  WHERE sow_embedding IS NOT NULL;

DROP TRIGGER IF EXISTS opportunities_touch_updated_at ON capture.opportunities;
CREATE TRIGGER opportunities_touch_updated_at
BEFORE UPDATE ON capture.opportunities
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.awards (
  award_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_award_unique_key text NOT NULL,
  piid text NOT NULL,
  referenced_idv_piid text,
  parent_award_id uuid REFERENCES capture.awards(award_id) ON DELETE SET NULL,
  opportunity_id uuid REFERENCES capture.opportunities(opportunity_id) ON DELETE SET NULL,
  prime_entity_id uuid NOT NULL REFERENCES capture.entities(entity_id) ON DELETE RESTRICT,
  award_number text,
  award_type text,
  title text,
  description text,
  signed_date date,
  period_of_performance_start date,
  period_of_performance_end date,
  awarding_agency_name text,
  awarding_agency_code text,
  funding_agency_name text,
  funding_agency_code text,
  contracting_office_name text,
  contracting_office_code text,
  naics_code varchar(6),
  psc_code varchar(4),
  set_aside_code text,
  total_obligation numeric(18,2),
  current_total_value numeric(18,2),
  potential_total_value numeric(18,2),
  description_embedding vector(1536),
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT awards_contract_award_unique_key_uq UNIQUE (contract_award_unique_key),
  CHECK (naics_code IS NULL OR naics_code ~ '^[0-9]{2,6}$'),
  CHECK (psc_code IS NULL OR length(psc_code) BETWEEN 1 AND 4),
  CHECK (total_obligation IS NULL OR total_obligation >= 0),
  CHECK (current_total_value IS NULL OR current_total_value >= 0),
  CHECK (potential_total_value IS NULL OR potential_total_value >= 0)
);

CREATE INDEX IF NOT EXISTS awards_piid_idx
  ON capture.awards (piid);

CREATE INDEX IF NOT EXISTS awards_referenced_idv_piid_idx
  ON capture.awards (referenced_idv_piid);

CREATE INDEX IF NOT EXISTS awards_prime_entity_idx
  ON capture.awards (prime_entity_id);

CREATE INDEX IF NOT EXISTS awards_opportunity_idx
  ON capture.awards (opportunity_id);

CREATE INDEX IF NOT EXISTS awards_signed_date_idx
  ON capture.awards (signed_date DESC);

CREATE INDEX IF NOT EXISTS awards_agency_idx
  ON capture.awards (funding_agency_code, awarding_agency_code);

CREATE INDEX IF NOT EXISTS awards_naics_psc_idx
  ON capture.awards (naics_code, psc_code);

CREATE INDEX IF NOT EXISTS awards_value_idx
  ON capture.awards (total_obligation DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS awards_description_embedding_hnsw_idx
  ON capture.awards
  USING hnsw (description_embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 96)
  WHERE description_embedding IS NOT NULL;

DROP TRIGGER IF EXISTS awards_touch_updated_at ON capture.awards;
CREATE TRIGGER awards_touch_updated_at
BEFORE UPDATE ON capture.awards
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.sub_awards (
  sub_award_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fsrs_report_id text,
  award_id uuid NOT NULL REFERENCES capture.awards(award_id) ON DELETE CASCADE,
  prime_entity_id uuid NOT NULL REFERENCES capture.entities(entity_id) ON DELETE RESTRICT,
  subcontractor_entity_id uuid NOT NULL REFERENCES capture.entities(entity_id) ON DELETE RESTRICT,
  parent_sub_award_id uuid REFERENCES capture.sub_awards(sub_award_id) ON DELETE SET NULL,
  relationship_path uuid[] NOT NULL DEFAULT '{}'::uuid[],
  tier integer NOT NULL DEFAULT 1 CHECK (tier >= 1),
  subaward_number text,
  action_date date,
  amount numeric(18,2) CHECK (amount IS NULL OR amount >= 0),
  description text,
  naics_code varchar(6),
  psc_code varchar(4),
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (prime_entity_id <> subcontractor_entity_id),
  CHECK (naics_code IS NULL OR naics_code ~ '^[0-9]{2,6}$'),
  CHECK (psc_code IS NULL OR length(psc_code) BETWEEN 1 AND 4)
);

CREATE UNIQUE INDEX IF NOT EXISTS sub_awards_natural_uq
  ON capture.sub_awards (
    award_id,
    prime_entity_id,
    subcontractor_entity_id,
    coalesce(subaward_number, ''),
    coalesce(fsrs_report_id, '')
  );

CREATE INDEX IF NOT EXISTS sub_awards_award_idx
  ON capture.sub_awards (award_id);

CREATE INDEX IF NOT EXISTS sub_awards_prime_entity_idx
  ON capture.sub_awards (prime_entity_id);

CREATE INDEX IF NOT EXISTS sub_awards_subcontractor_entity_idx
  ON capture.sub_awards (subcontractor_entity_id);

CREATE INDEX IF NOT EXISTS sub_awards_parent_sub_award_idx
  ON capture.sub_awards (parent_sub_award_id);

CREATE INDEX IF NOT EXISTS sub_awards_relationship_path_gin_idx
  ON capture.sub_awards USING gin (relationship_path);

CREATE INDEX IF NOT EXISTS sub_awards_action_date_idx
  ON capture.sub_awards (action_date DESC);

CREATE INDEX IF NOT EXISTS sub_awards_naics_psc_idx
  ON capture.sub_awards (naics_code, psc_code);

DROP TRIGGER IF EXISTS sub_awards_touch_updated_at ON capture.sub_awards;
CREATE TRIGGER sub_awards_touch_updated_at
BEFORE UPDATE ON capture.sub_awards
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

COMMIT;
