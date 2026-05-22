BEGIN;

CREATE TABLE IF NOT EXISTS capture.calc_labor_rates (
  labor_rate_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  labor_category text NOT NULL,
  normalized_labor_category text NOT NULL,
  education_level text NOT NULL,
  min_years_experience integer NOT NULL CHECK (min_years_experience >= 0),
  site text NOT NULL CHECK (site IN ('CONUS', 'OCONUS', 'Remote')),
  schedule text NOT NULL,
  naics_code varchar(6),
  psc_code varchar(4),
  ceiling_hourly_rate numeric(10,2) NOT NULL CHECK (ceiling_hourly_rate > 0),
  percentile_50_hourly_rate numeric(10,2) NOT NULL CHECK (percentile_50_hourly_rate > 0),
  percentile_75_hourly_rate numeric(10,2) NOT NULL CHECK (percentile_75_hourly_rate > 0),
  source text NOT NULL DEFAULT 'CALC+',
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (naics_code IS NULL OR naics_code ~ '^[0-9]{2,6}$'),
  CHECK (psc_code IS NULL OR length(psc_code) BETWEEN 1 AND 4)
);

CREATE UNIQUE INDEX IF NOT EXISTS calc_labor_rates_natural_uq
  ON capture.calc_labor_rates (
    normalized_labor_category,
    education_level,
    min_years_experience,
    site,
    schedule,
    coalesce(naics_code, ''),
    coalesce(psc_code, '')
  );

CREATE INDEX IF NOT EXISTS calc_labor_rates_category_idx
  ON capture.calc_labor_rates (normalized_labor_category);

CREATE INDEX IF NOT EXISTS calc_labor_rates_naics_psc_idx
  ON capture.calc_labor_rates (naics_code, psc_code);

CREATE INDEX IF NOT EXISTS calc_labor_rates_ceiling_idx
  ON capture.calc_labor_rates (ceiling_hourly_rate DESC);

DROP TRIGGER IF EXISTS calc_labor_rates_touch_updated_at ON capture.calc_labor_rates;
CREATE TRIGGER calc_labor_rates_touch_updated_at
BEFORE UPDATE ON capture.calc_labor_rates
FOR EACH ROW
EXECUTE FUNCTION capture.touch_updated_at();

COMMIT;
