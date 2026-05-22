BEGIN;

ALTER TABLE capture.tenants
  ADD COLUMN IF NOT EXISTS auth_provider text NOT NULL DEFAULT 'demo',
  ADD COLUMN IF NOT EXISTS auth_issuer text,
  ADD COLUMN IF NOT EXISTS auth_audience text,
  ADD COLUMN IF NOT EXISTS required_mfa boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS data_retention_days integer NOT NULL DEFAULT 365 CHECK (data_retention_days > 0),
  ADD COLUMN IF NOT EXISTS privacy_contact_email text;

CREATE TABLE IF NOT EXISTS capture.customer_past_performance (
  past_performance_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES capture.tenants(tenant_id) ON DELETE CASCADE,
  customer_profile_id uuid REFERENCES capture.customer_profiles(customer_profile_id) ON DELETE SET NULL,
  source text NOT NULL DEFAULT 'customer_import',
  contract_number text NOT NULL,
  role text NOT NULL CHECK (role IN ('prime', 'subcontractor', 'mentor_protege', 'joint_venture')),
  prime_name text,
  agency_name text,
  agency_code text,
  naics_code varchar(6),
  psc_code varchar(4),
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  start_date date,
  end_date date,
  obligated_amount numeric(18,2) CHECK (obligated_amount IS NULL OR obligated_amount >= 0),
  contract_vehicles text[] NOT NULL DEFAULT '{}'::text[],
  clearance_required text,
  customer_rating text,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, contract_number, role)
);

CREATE INDEX IF NOT EXISTS customer_past_performance_tenant_idx
  ON capture.customer_past_performance (tenant_id, agency_code, naics_code, psc_code);

CREATE INDEX IF NOT EXISTS customer_past_performance_value_idx
  ON capture.customer_past_performance (tenant_id, obligated_amount DESC NULLS LAST);

DROP TRIGGER IF EXISTS customer_past_performance_touch_updated_at ON capture.customer_past_performance;
CREATE TRIGGER customer_past_performance_touch_updated_at
BEFORE UPDATE ON capture.customer_past_performance
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.billing_accounts (
  billing_account_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL UNIQUE REFERENCES capture.tenants(tenant_id) ON DELETE CASCADE,
  billing_provider text NOT NULL DEFAULT 'stripe' CHECK (billing_provider IN ('stripe', 'manual')),
  provider_customer_id text,
  provider_subscription_id text,
  subscription_status text NOT NULL DEFAULT 'trialing'
    CHECK (subscription_status IN ('trialing', 'active', 'past_due', 'canceled', 'unpaid', 'incomplete')),
  price_id text,
  trial_ends_at timestamptz,
  current_period_ends_at timestamptz,
  billing_email text,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS billing_accounts_status_idx
  ON capture.billing_accounts (subscription_status, current_period_ends_at);

DROP TRIGGER IF EXISTS billing_accounts_touch_updated_at ON capture.billing_accounts;
CREATE TRIGGER billing_accounts_touch_updated_at
BEFORE UPDATE ON capture.billing_accounts
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.billing_events (
  billing_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid REFERENCES capture.tenants(tenant_id) ON DELETE SET NULL,
  provider text NOT NULL DEFAULT 'stripe',
  provider_event_id text UNIQUE,
  event_type text NOT NULL,
  event_payload jsonb NOT NULL,
  processed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS billing_events_tenant_processed_idx
  ON capture.billing_events (tenant_id, processed_at DESC);

CREATE TABLE IF NOT EXISTS capture.ingest_runs (
  ingest_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system text NOT NULL,
  dataset_name text NOT NULL,
  run_status text NOT NULL CHECK (run_status IN ('started', 'succeeded', 'failed')),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  records_read integer NOT NULL DEFAULT 0 CHECK (records_read >= 0),
  records_written integer NOT NULL DEFAULT 0 CHECK (records_written >= 0),
  error_message text,
  run_config jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ingest_runs_source_started_idx
  ON capture.ingest_runs (source_system, dataset_name, started_at DESC);

CREATE TABLE IF NOT EXISTS capture.compliance_controls (
  control_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  control_key text NOT NULL UNIQUE,
  control_family text NOT NULL,
  control_name text NOT NULL,
  implementation_status text NOT NULL CHECK (implementation_status IN ('planned', 'implemented', 'compensating', 'not_applicable')),
  implementation_notes text NOT NULL DEFAULT '',
  evidence_url text,
  owner text NOT NULL DEFAULT 'platform',
  updated_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
