BEGIN;

CREATE TABLE IF NOT EXISTS capture.consultant_brand_settings (
  tenant_id uuid PRIMARY KEY REFERENCES capture.tenants(tenant_id) ON DELETE CASCADE,
  organization_name text NOT NULL DEFAULT 'GovCon Advisory Practice',
  logo_url text,
  primary_color text NOT NULL DEFAULT '#0f766e',
  report_footer text NOT NULL DEFAULT 'Prepared by your GovCon advisor. Decision support only; not legal or procurement advice.',
  support_email text,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (primary_color ~ '^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$'),
  CHECK (logo_url IS NULL OR logo_url ~ '^https?://')
);

ALTER TABLE capture.consultant_brand_settings
  DROP CONSTRAINT IF EXISTS consultant_brand_settings_primary_color_check;

ALTER TABLE capture.consultant_brand_settings
  ADD CONSTRAINT consultant_brand_settings_primary_color_check
  CHECK (primary_color ~ '^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$');

DROP TRIGGER IF EXISTS consultant_brand_settings_touch_updated_at ON capture.consultant_brand_settings;
CREATE TRIGGER consultant_brand_settings_touch_updated_at
BEFORE UPDATE ON capture.consultant_brand_settings
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

CREATE TABLE IF NOT EXISTS capture.consultant_reminders (
  reminder_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES capture.tenants(tenant_id) ON DELETE CASCADE,
  opportunity_id uuid REFERENCES capture.opportunities(opportunity_id) ON DELETE CASCADE,
  owner_user_id uuid REFERENCES capture.tenant_users(user_id) ON DELETE SET NULL,
  reminder_type text NOT NULL DEFAULT 'client_follow_up'
    CHECK (reminder_type IN ('client_follow_up', 'deadline', 'document_request', 'proposal_task', 'renewal', 'billing')),
  title text NOT NULL CHECK (length(trim(title)) > 0),
  body text NOT NULL DEFAULT '',
  due_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'snoozed', 'canceled')),
  client_visible boolean NOT NULL DEFAULT false,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS consultant_reminders_tenant_due_idx
  ON capture.consultant_reminders (tenant_id, status, due_at);

CREATE INDEX IF NOT EXISTS consultant_reminders_opportunity_idx
  ON capture.consultant_reminders (opportunity_id);

DROP TRIGGER IF EXISTS consultant_reminders_touch_updated_at ON capture.consultant_reminders;
CREATE TRIGGER consultant_reminders_touch_updated_at
BEFORE UPDATE ON capture.consultant_reminders
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

COMMIT;
