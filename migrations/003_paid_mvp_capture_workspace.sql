BEGIN;

CREATE TABLE IF NOT EXISTS capture.tenants (
  tenant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_slug text NOT NULL UNIQUE,
  tenant_name text NOT NULL,
  plan_tier text NOT NULL DEFAULT 'demo' CHECK (plan_tier IN ('demo', 'team', 'enterprise')),
  data_region text NOT NULL DEFAULT 'us-east-1',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (tenant_slug ~ '^[a-z0-9][a-z0-9-]{2,62}$')
);

DROP TRIGGER IF EXISTS tenants_touch_updated_at ON capture.tenants;
CREATE TRIGGER tenants_touch_updated_at
BEFORE UPDATE ON capture.tenants
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.tenant_users (
  user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES capture.tenants(tenant_id) ON DELETE CASCADE,
  email text NOT NULL,
  display_name text NOT NULL,
  role text NOT NULL CHECK (role IN ('admin', 'capture_manager', 'analyst', 'viewer')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'invited', 'disabled')),
  last_seen_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS tenant_users_tenant_email_uq
  ON capture.tenant_users (tenant_id, lower(email));

CREATE INDEX IF NOT EXISTS tenant_users_tenant_role_idx
  ON capture.tenant_users (tenant_id, role);

DROP TRIGGER IF EXISTS tenant_users_touch_updated_at ON capture.tenant_users;
CREATE TRIGGER tenant_users_touch_updated_at
BEFORE UPDATE ON capture.tenant_users
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.customer_profiles (
  customer_profile_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES capture.tenants(tenant_id) ON DELETE CASCADE,
  entity_id uuid REFERENCES capture.entities(entity_id) ON DELETE SET NULL,
  company_name text NOT NULL,
  target_naics_codes text[] NOT NULL DEFAULT '{}'::text[],
  target_psc_codes text[] NOT NULL DEFAULT '{}'::text[],
  target_agency_codes text[] NOT NULL DEFAULT '{}'::text[],
  contract_vehicles text[] NOT NULL DEFAULT '{}'::text[],
  set_aside_eligibilities text[] NOT NULL DEFAULT '{}'::text[],
  clearance_levels text[] NOT NULL DEFAULT '{}'::text[],
  socioeconomic_tags text[] NOT NULL DEFAULT '{}'::text[],
  incumbent_agency_codes text[] NOT NULL DEFAULT '{}'::text[],
  past_performance_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  pricing_strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
  risk_preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, company_name)
);

CREATE INDEX IF NOT EXISTS customer_profiles_tenant_idx
  ON capture.customer_profiles (tenant_id);

CREATE INDEX IF NOT EXISTS customer_profiles_entity_idx
  ON capture.customer_profiles (entity_id);

CREATE INDEX IF NOT EXISTS customer_profiles_codes_gin_idx
  ON capture.customer_profiles USING gin (target_naics_codes, target_psc_codes, target_agency_codes);

DROP TRIGGER IF EXISTS customer_profiles_touch_updated_at ON capture.customer_profiles;
CREATE TRIGGER customer_profiles_touch_updated_at
BEFORE UPDATE ON capture.customer_profiles
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.capture_opportunity_workflow (
  workflow_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES capture.tenants(tenant_id) ON DELETE CASCADE,
  opportunity_id uuid NOT NULL REFERENCES capture.opportunities(opportunity_id) ON DELETE CASCADE,
  owner_user_id uuid REFERENCES capture.tenant_users(user_id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'tracking' CHECK (status IN ('tracking', 'qualifying', 'bid', 'no_bid', 'submitted', 'won', 'lost')),
  go_no_go text NOT NULL DEFAULT 'undecided' CHECK (go_no_go IN ('go', 'no_go', 'undecided')),
  priority text NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
  stage text NOT NULL DEFAULT 'Qualification',
  next_review_at timestamptz,
  due_at timestamptz,
  tags text[] NOT NULL DEFAULT '{}'::text[],
  notes text NOT NULL DEFAULT '',
  decision_rationale text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, opportunity_id)
);

CREATE INDEX IF NOT EXISTS capture_workflow_tenant_status_idx
  ON capture.capture_opportunity_workflow (tenant_id, status, priority);

CREATE INDEX IF NOT EXISTS capture_workflow_due_idx
  ON capture.capture_opportunity_workflow (tenant_id, due_at);

DROP TRIGGER IF EXISTS capture_workflow_touch_updated_at ON capture.capture_opportunity_workflow;
CREATE TRIGGER capture_workflow_touch_updated_at
BEFORE UPDATE ON capture.capture_opportunity_workflow
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.opportunity_notes (
  note_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES capture.tenants(tenant_id) ON DELETE CASCADE,
  opportunity_id uuid NOT NULL REFERENCES capture.opportunities(opportunity_id) ON DELETE CASCADE,
  author_user_id uuid REFERENCES capture.tenant_users(user_id) ON DELETE SET NULL,
  note_type text NOT NULL DEFAULT 'capture_note' CHECK (note_type IN ('capture_note', 'risk', 'customer_call', 'price_to_win', 'teaming')),
  body text NOT NULL CHECK (length(trim(body)) > 0),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS opportunity_notes_lookup_idx
  ON capture.opportunity_notes (tenant_id, opportunity_id, created_at DESC);

CREATE TABLE IF NOT EXISTS capture.competitor_watchlist (
  watchlist_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES capture.tenants(tenant_id) ON DELETE CASCADE,
  entity_id uuid NOT NULL REFERENCES capture.entities(entity_id) ON DELETE CASCADE,
  reason text NOT NULL DEFAULT '',
  priority text NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, entity_id)
);

CREATE INDEX IF NOT EXISTS competitor_watchlist_tenant_idx
  ON capture.competitor_watchlist (tenant_id, priority);

DROP TRIGGER IF EXISTS competitor_watchlist_touch_updated_at ON capture.competitor_watchlist;
CREATE TRIGGER competitor_watchlist_touch_updated_at
BEFORE UPDATE ON capture.competitor_watchlist
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.data_freshness (
  freshness_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system text NOT NULL,
  dataset_name text NOT NULL,
  source_mode text NOT NULL DEFAULT 'mock_seed' CHECK (source_mode IN ('live_api', 'mock_seed', 'manual_import')),
  last_successful_sync_at timestamptz,
  last_attempted_sync_at timestamptz,
  sync_status text NOT NULL DEFAULT 'ready' CHECK (sync_status IN ('ready', 'syncing', 'degraded', 'failed')),
  record_count integer NOT NULL DEFAULT 0 CHECK (record_count >= 0),
  freshness_sla_hours integer NOT NULL DEFAULT 24 CHECK (freshness_sla_hours > 0),
  source_url text,
  notes text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_system, dataset_name)
);

CREATE INDEX IF NOT EXISTS data_freshness_status_idx
  ON capture.data_freshness (sync_status, last_successful_sync_at DESC);

DROP TRIGGER IF EXISTS data_freshness_touch_updated_at ON capture.data_freshness;
CREATE TRIGGER data_freshness_touch_updated_at
BEFORE UPDATE ON capture.data_freshness
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.source_evidence (
  evidence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  opportunity_id uuid REFERENCES capture.opportunities(opportunity_id) ON DELETE CASCADE,
  award_id uuid REFERENCES capture.awards(award_id) ON DELETE CASCADE,
  sub_award_id uuid REFERENCES capture.sub_awards(sub_award_id) ON DELETE CASCADE,
  labor_rate_id uuid REFERENCES capture.calc_labor_rates(labor_rate_id) ON DELETE CASCADE,
  related_entity_id uuid REFERENCES capture.entities(entity_id) ON DELETE SET NULL,
  evidence_type text NOT NULL CHECK (evidence_type IN ('opportunity', 'award', 'subaward', 'labor_rate', 'entity', 'score_factor')),
  source_system text NOT NULL,
  source_record_id text,
  source_title text NOT NULL,
  source_url text,
  source_record_date date,
  source_amount numeric(18,2),
  agency_name text,
  agency_code text,
  naics_code varchar(6),
  psc_code varchar(4),
  explanation text NOT NULL DEFAULT '',
  confidence numeric(5,4) NOT NULL DEFAULT 1.0000 CHECK (confidence >= 0 AND confidence <= 1),
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (source_url IS NULL OR source_url ~ '^https?://')
);

CREATE INDEX IF NOT EXISTS source_evidence_opportunity_type_idx
  ON capture.source_evidence (opportunity_id, evidence_type);

CREATE INDEX IF NOT EXISTS source_evidence_award_idx
  ON capture.source_evidence (award_id);

CREATE INDEX IF NOT EXISTS source_evidence_sub_award_idx
  ON capture.source_evidence (sub_award_id);

CREATE INDEX IF NOT EXISTS source_evidence_labor_rate_idx
  ON capture.source_evidence (labor_rate_id);

CREATE INDEX IF NOT EXISTS source_evidence_entity_idx
  ON capture.source_evidence (related_entity_id);

DROP TRIGGER IF EXISTS source_evidence_touch_updated_at ON capture.source_evidence;
CREATE TRIGGER source_evidence_touch_updated_at
BEFORE UPDATE ON capture.source_evidence
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.audit_events (
  audit_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid REFERENCES capture.tenants(tenant_id) ON DELETE SET NULL,
  actor_user_id uuid REFERENCES capture.tenant_users(user_id) ON DELETE SET NULL,
  actor_email text,
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id text,
  ip_address inet,
  user_agent text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_events_tenant_created_idx
  ON capture.audit_events (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS audit_events_resource_idx
  ON capture.audit_events (resource_type, resource_id);

COMMIT;
