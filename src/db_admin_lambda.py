from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Mapping

import psycopg2

from .mock_data_seeder import seed_mock_data


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "migrations"


def lambda_handler(event: Mapping[str, Any], context: Any) -> Dict[str, Any]:
    action = str(event.get("action", "migrate_and_seed"))
    reset = bool(event.get("reset", False))

    if action not in {"migrate", "seed", "migrate_and_seed", "cleanup_sam_mock_seed", "seed_demo_customer_teams"}:
        raise ValueError("action must be one of: migrate, seed, migrate_and_seed, cleanup_sam_mock_seed, seed_demo_customer_teams")

    result: Dict[str, Any] = {"action": action}

    if action in {"migrate", "migrate_and_seed"}:
        result["migrations"] = apply_migrations(os.environ["DATABASE_URL"])

    if action in {"seed", "migrate_and_seed"}:
        result["seeded"] = seed_mock_data(os.environ["DATABASE_URL"], reset=reset)

    if action == "cleanup_sam_mock_seed":
        result["cleanup"] = cleanup_sam_mock_seed(os.environ["DATABASE_URL"])

    if action == "seed_demo_customer_teams":
        result["customer_teams"] = seed_demo_customer_teams(os.environ["DATABASE_URL"])

    LOGGER.info("DB admin completed: %s", json.dumps(result, sort_keys=True))
    return result


def apply_migrations(database_url: str) -> list[str]:
    migration_paths = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_paths:
        raise FileNotFoundError(f"No SQL migrations found in {MIGRATIONS_DIR}")

    applied = []
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for path in migration_paths:
                LOGGER.info("Applying migration %s", path.name)
                cur.execute(path.read_text(encoding="utf-8"))
                applied.append(path.name)
    return applied


def cleanup_sam_mock_seed(database_url: str) -> Dict[str, int]:
    """Remove seeded SAM opportunity rows after live SAM.gov ingest is enabled."""
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH target_opportunities AS (
                  SELECT opportunity_id
                  FROM capture.opportunities
                  WHERE notice_id LIKE 'SAM-2026-%'
                     OR source_payload @> '{"mock_seed": true}'::jsonb
                     OR source_payload->>'source_mode' = 'mock_seed'
                ),
                deleted_opportunities AS (
                  DELETE FROM capture.opportunities o
                  USING target_opportunities t
                  WHERE o.opportunity_id = t.opportunity_id
                  RETURNING o.opportunity_id
                )
                SELECT count(*)::int FROM deleted_opportunities;
                """
            )
            deleted_opportunities = int(cur.fetchone()[0])

            cur.execute(
                """
                DELETE FROM capture.data_freshness
                WHERE source_system = 'SAM.gov'
                  AND source_mode = 'mock_seed'
                RETURNING freshness_id;
                """
            )
            deleted_sam_freshness_rows = cur.rowcount

            cur.execute(
                """
                SELECT count(*)::int
                FROM capture.opportunities
                WHERE source_payload ? 'noticeId'
                   OR source_payload ? 'notice_id'
                   OR ui_link ILIKE '%sam.gov%'
                   OR description_url ILIKE '%sam.gov%';
                """
            )
            live_sam_opportunities = int(cur.fetchone()[0])

            if live_sam_opportunities:
                cur.execute(
                    """
                    INSERT INTO capture.data_freshness (
                      source_system, dataset_name, source_mode, last_successful_sync_at,
                      last_attempted_sync_at, sync_status, record_count, freshness_sla_hours,
                      source_url, notes
                    )
                    VALUES (
                      'SAM.gov',
                      'Opportunities',
                      'live_api',
                      now(),
                      now(),
                      'ready',
                      %(record_count)s,
                      6,
                      'https://api.sam.gov/opportunities/v2/search',
                      'Live SAM.gov Opportunities API records. Seeded SAM demo opportunities have been removed.'
                    )
                    ON CONFLICT (source_system, dataset_name)
                    DO UPDATE SET
                      source_mode = 'live_api',
                      last_successful_sync_at = COALESCE(capture.data_freshness.last_successful_sync_at, EXCLUDED.last_successful_sync_at),
                      last_attempted_sync_at = COALESCE(capture.data_freshness.last_attempted_sync_at, EXCLUDED.last_attempted_sync_at),
                      sync_status = 'ready',
                      record_count = EXCLUDED.record_count,
                      freshness_sla_hours = EXCLUDED.freshness_sla_hours,
                      source_url = EXCLUDED.source_url,
                      notes = EXCLUDED.notes,
                      updated_at = now();
                    """,
                    {"record_count": live_sam_opportunities},
                )

    return {
        "deleted_sam_mock_opportunities": deleted_opportunities,
        "deleted_sam_mock_freshness_rows": deleted_sam_freshness_rows,
        "live_sam_opportunities": live_sam_opportunities,
    }


def seed_demo_customer_teams(database_url: str) -> Dict[str, int]:
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH tenant AS (
                  INSERT INTO capture.tenants (
                    tenant_slug, tenant_name, plan_tier, data_region,
                    auth_provider, required_mfa, data_retention_days, privacy_contact_email
                  )
                  VALUES (
                    'metal-fabrication-shop',
                    'Keystone Metal Fabrication Shop',
                    'demo',
                    'us-east-1',
                    'demo',
                    false,
                    365,
                    'privacy@keystonemetal.example'
                  )
                  ON CONFLICT (tenant_slug)
                  DO UPDATE SET
                    tenant_name = EXCLUDED.tenant_name,
                    plan_tier = EXCLUDED.plan_tier,
                    data_region = EXCLUDED.data_region,
                    auth_provider = EXCLUDED.auth_provider,
                    required_mfa = EXCLUDED.required_mfa,
                    data_retention_days = EXCLUDED.data_retention_days,
                    privacy_contact_email = EXCLUDED.privacy_contact_email,
                    updated_at = now()
                  RETURNING tenant_id
                ),
                entity AS (
                  INSERT INTO capture.entities (
                    legal_name, alias_names, source_system, source_payload
                  )
                  VALUES (
                    'Keystone Metal Fabrication Shop',
                    ARRAY[
                      'Keystone Metal Fab',
                      'Keystone Fabrication',
                      'Keystone Precision Weldments',
                      'Keystone Machine and Fab'
                    ]::text[],
                    'manual_import',
                    '{"demo_customer_profile": true, "business_type": "metal_fabrication"}'::jsonb
                  )
                  ON CONFLICT (normalized_legal_name)
                  DO UPDATE SET
                    alias_names = EXCLUDED.alias_names,
                    source_system = EXCLUDED.source_system,
                    source_payload = capture.entities.source_payload || EXCLUDED.source_payload,
                    updated_at = now()
                  RETURNING entity_id
                ),
                lead_user AS (
                  INSERT INTO capture.tenant_users (
                    tenant_id, email, display_name, role, status, last_seen_at
                  )
                  SELECT
                    tenant.tenant_id,
                    'owner@keystonemetal.example',
                    'Metal Fabrication Owner',
                    'capture_manager',
                    'active',
                    now()
                  FROM tenant
                  ON CONFLICT (tenant_id, (lower(email)))
                  DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    last_seen_at = EXCLUDED.last_seen_at,
                    updated_at = now()
                  RETURNING user_id
                ),
                analyst_user AS (
                  INSERT INTO capture.tenant_users (
                    tenant_id, email, display_name, role, status, last_seen_at
                  )
                  SELECT
                    tenant.tenant_id,
                    'estimator@keystonemetal.example',
                    'Fabrication Estimator',
                    'analyst',
                    'active',
                    now()
                  FROM tenant
                  ON CONFLICT (tenant_id, (lower(email)))
                  DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    last_seen_at = EXCLUDED.last_seen_at,
                    updated_at = now()
                  RETURNING user_id
                ),
                profile AS (
                  INSERT INTO capture.customer_profiles (
                    tenant_id, entity_id, company_name, target_naics_codes,
                    target_psc_codes, target_agency_codes, contract_vehicles,
                    set_aside_eligibilities, clearance_levels, socioeconomic_tags,
                    incumbent_agency_codes, past_performance_summary,
                    pricing_strategy, risk_preferences
                  )
                  SELECT
                    tenant.tenant_id,
                    entity.entity_id,
                    'Keystone Metal Fabrication Shop',
                    ARRAY['332312','332313','332322','332710','332999','336413']::text[],
                    ARRAY['1560','1730','5340','5450','9520','9530','9540']::text[],
                    ARRAY['097','017','021','057']::text[],
                    ARRAY['DIBBS', 'SAM.gov Open Market', 'GSA MAS Industrial Products']::text[],
                    ARRAY['Small Business']::text[],
                    ARRAY['Facility access eligible']::text[],
                    ARRAY['Metal fabrication', 'CNC machining', 'Welding', 'Sheet metal']::text[],
                    ARRAY['097','017']::text[],
                    '{
                      "prime_contracts": 4,
                      "subcontracts": 1,
                      "recent_relevant_obligation": 4650000,
                      "strongest_domains": ["fabricated_structural_metal", "machined_components", "defense_spares"],
                      "agency_relationships": {
                        "097": "DLA small business supplier for fabricated brackets, plates, and repair parts",
                        "017": "Navy shipboard stainless and aluminum fabrication support",
                        "021": "Army ground support equipment weldments and assemblies"
                      }
                    }'::jsonb,
                    '{
                      "target_blend_discount_to_calc_p75": 0.12,
                      "preferred_labor_mix": "journeyman welders, CNC operators, and estimator-led QA"
                    }'::jsonb,
                    '{
                      "max_single_award_value": 8000000,
                      "avoid_no_incumbent_access": true,
                      "needs_prime_partner_above": 12000000
                    }'::jsonb
                  FROM tenant
                  CROSS JOIN entity
                  ON CONFLICT (tenant_id, company_name)
                  DO UPDATE SET
                    entity_id = EXCLUDED.entity_id,
                    target_naics_codes = EXCLUDED.target_naics_codes,
                    target_psc_codes = EXCLUDED.target_psc_codes,
                    target_agency_codes = EXCLUDED.target_agency_codes,
                    contract_vehicles = EXCLUDED.contract_vehicles,
                    set_aside_eligibilities = EXCLUDED.set_aside_eligibilities,
                    clearance_levels = EXCLUDED.clearance_levels,
                    socioeconomic_tags = EXCLUDED.socioeconomic_tags,
                    incumbent_agency_codes = EXCLUDED.incumbent_agency_codes,
                    past_performance_summary = EXCLUDED.past_performance_summary,
                    pricing_strategy = EXCLUDED.pricing_strategy,
                    risk_preferences = EXCLUDED.risk_preferences,
                    updated_at = now()
                  RETURNING customer_profile_id, tenant_id
                ),
                past_performance_rows AS (
                  SELECT *
                  FROM (
                    VALUES
                      ('KEY-DLA-24-001', 'prime', NULL, 'Defense Logistics Agency', '097', '332710', '5340', 'CNC Machined Aluminum Bracket Kits', 'Precision machined and anodized aluminum bracket kits for depot-level repair stock.', 740000.00, ARRAY['DIBBS']::text[], 'None', 'Very Good'),
                      ('KEY-NAVSEA-23-014', 'prime', NULL, 'Department of the Navy', '017', '332312', '5450', 'Shipboard Stainless Guard Assemblies', 'Welded stainless guard, ladder, and access assemblies for ship maintenance availability.', 1260000.00, ARRAY['SAM.gov Open Market']::text[], 'Facility access eligible', 'Exceptional'),
                      ('KEY-ARMY-25-007', 'prime', NULL, 'Department of the Army', '021', '332313', '1730', 'Ground Support Equipment Weldments', 'Fabricated steel weldments, powder coating, and dimensional inspection for ground support fixtures.', 980000.00, ARRAY['SAM.gov Open Market']::text[], 'None', 'Very Good'),
                      ('KEY-USAF-24-019', 'subcontractor', 'Aerospace Structures Integrator LLC', 'Department of the Air Force', '057', '336413', '1560', 'Aircraft Maintenance Stand Components', 'Laser-cut panels, formed sheet metal components, and welded subassemblies for maintenance stands.', 1670000.00, ARRAY['Prime subcontract']::text[], 'Facility access eligible', 'Exceptional')
                  ) AS rows(
                    contract_number, role, prime_name, agency_name, agency_code,
                    naics_code, psc_code, title, description, obligated_amount,
                    contract_vehicles, clearance_required, customer_rating
                  )
                ),
                upsert_past_performance AS (
                  INSERT INTO capture.customer_past_performance (
                    tenant_id, customer_profile_id, source, contract_number,
                    role, prime_name, agency_name, agency_code, naics_code,
                    psc_code, title, description, start_date, end_date,
                    obligated_amount, contract_vehicles, clearance_required,
                    customer_rating, source_payload
                  )
                  SELECT
                    profile.tenant_id,
                    profile.customer_profile_id,
                    'demo_customer_import',
                    rows.contract_number,
                    rows.role,
                    rows.prime_name,
                    rows.agency_name,
                    rows.agency_code,
                    rows.naics_code,
                    rows.psc_code,
                    rows.title,
                    rows.description,
                    DATE '2024-01-01',
                    DATE '2026-12-31',
                    rows.obligated_amount,
                    rows.contract_vehicles,
                    rows.clearance_required,
                    rows.customer_rating,
                    jsonb_build_object('demo_customer_profile', true, 'business_type', 'metal_fabrication')
                  FROM profile
                  CROSS JOIN past_performance_rows rows
                  ON CONFLICT (tenant_id, contract_number, role)
                  DO UPDATE SET
                    customer_profile_id = EXCLUDED.customer_profile_id,
                    source = EXCLUDED.source,
                    prime_name = EXCLUDED.prime_name,
                    agency_name = EXCLUDED.agency_name,
                    agency_code = EXCLUDED.agency_code,
                    naics_code = EXCLUDED.naics_code,
                    psc_code = EXCLUDED.psc_code,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    obligated_amount = EXCLUDED.obligated_amount,
                    contract_vehicles = EXCLUDED.contract_vehicles,
                    clearance_required = EXCLUDED.clearance_required,
                    customer_rating = EXCLUDED.customer_rating,
                    source_payload = EXCLUDED.source_payload,
                    updated_at = now()
                  RETURNING past_performance_id
                ),
                upsert_billing AS (
                  INSERT INTO capture.billing_accounts (
                    tenant_id, billing_provider, provider_customer_id,
                    provider_subscription_id, subscription_status, price_id,
                    trial_ends_at, current_period_ends_at, billing_email,
                    source_payload
                  )
                  SELECT
                    tenant.tenant_id,
                    'manual',
                    'cus_demo_metal_fabrication',
                    'sub_demo_metal_fabrication',
                    'trialing',
                    'price_captureos_shop_demo',
                    now() + INTERVAL '30 days',
                    now() + INTERVAL '30 days',
                    'billing@keystonemetal.example',
                    '{"demo_customer_profile": true}'::jsonb
                  FROM tenant
                  ON CONFLICT (tenant_id)
                  DO UPDATE SET
                    billing_provider = EXCLUDED.billing_provider,
                    provider_customer_id = EXCLUDED.provider_customer_id,
                    provider_subscription_id = EXCLUDED.provider_subscription_id,
                    subscription_status = EXCLUDED.subscription_status,
                    price_id = EXCLUDED.price_id,
                    trial_ends_at = EXCLUDED.trial_ends_at,
                    current_period_ends_at = EXCLUDED.current_period_ends_at,
                    billing_email = EXCLUDED.billing_email,
                    source_payload = EXCLUDED.source_payload,
                    updated_at = now()
                  RETURNING billing_account_id
                )
                SELECT
                  (SELECT count(*) FROM tenant)::int AS tenants,
                  (SELECT count(*) FROM profile)::int AS customer_profiles,
                  (SELECT count(*) FROM lead_user)::int + (SELECT count(*) FROM analyst_user)::int AS tenant_users,
                  (SELECT count(*) FROM upsert_past_performance)::int AS past_performance_rows,
                  (SELECT count(*) FROM upsert_billing)::int AS billing_accounts;
                """
            )
            metal_row = cur.fetchone()

            cur.execute(
                """
                WITH tenant AS (
                  INSERT INTO capture.tenants (
                    tenant_slug, tenant_name, plan_tier, data_region,
                    auth_provider, required_mfa, data_retention_days, privacy_contact_email
                  )
                  VALUES (
                    'construction-business',
                    'Construction Business',
                    'demo',
                    'us-east-1',
                    'demo',
                    false,
                    365,
                    'privacy@constructionbusiness.example'
                  )
                  ON CONFLICT (tenant_slug)
                  DO UPDATE SET
                    tenant_name = EXCLUDED.tenant_name,
                    plan_tier = EXCLUDED.plan_tier,
                    data_region = EXCLUDED.data_region,
                    auth_provider = EXCLUDED.auth_provider,
                    required_mfa = EXCLUDED.required_mfa,
                    data_retention_days = EXCLUDED.data_retention_days,
                    privacy_contact_email = EXCLUDED.privacy_contact_email,
                    updated_at = now()
                  RETURNING tenant_id
                ),
                entity AS (
                  INSERT INTO capture.entities (
                    legal_name, alias_names, source_system, source_payload
                  )
                  VALUES (
                    'Construction Business',
                    ARRAY[
                      'Construction Business LLC',
                      'Construction Business Federal',
                      'Construction Business Builders'
                    ]::text[],
                    'manual_import',
                    '{"demo_customer_profile": true, "business_type": "construction"}'::jsonb
                  )
                  ON CONFLICT (normalized_legal_name)
                  DO UPDATE SET
                    alias_names = EXCLUDED.alias_names,
                    source_system = EXCLUDED.source_system,
                    source_payload = capture.entities.source_payload || EXCLUDED.source_payload,
                    updated_at = now()
                  RETURNING entity_id
                ),
                lead_user AS (
                  INSERT INTO capture.tenant_users (
                    tenant_id, email, display_name, role, status, last_seen_at
                  )
                  SELECT
                    tenant.tenant_id,
                    'owner@constructionbusiness.example',
                    'Construction Owner',
                    'capture_manager',
                    'active',
                    now()
                  FROM tenant
                  ON CONFLICT (tenant_id, (lower(email)))
                  DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    last_seen_at = EXCLUDED.last_seen_at,
                    updated_at = now()
                  RETURNING user_id
                ),
                analyst_user AS (
                  INSERT INTO capture.tenant_users (
                    tenant_id, email, display_name, role, status, last_seen_at
                  )
                  SELECT
                    tenant.tenant_id,
                    'estimator@constructionbusiness.example',
                    'Construction Estimator',
                    'analyst',
                    'active',
                    now()
                  FROM tenant
                  ON CONFLICT (tenant_id, (lower(email)))
                  DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    last_seen_at = EXCLUDED.last_seen_at,
                    updated_at = now()
                  RETURNING user_id
                ),
                profile AS (
                  INSERT INTO capture.customer_profiles (
                    tenant_id, entity_id, company_name, target_naics_codes,
                    target_psc_codes, target_agency_codes, contract_vehicles,
                    set_aside_eligibilities, clearance_levels, socioeconomic_tags,
                    incumbent_agency_codes, past_performance_summary,
                    pricing_strategy, risk_preferences
                  )
                  SELECT
                    tenant.tenant_id,
                    entity.entity_id,
                    'Construction Business',
                    ARRAY['236220','237310','237990','238210','238220','238990']::text[],
                    ARRAY['Y1AA','Y1AZ','Y1QA','Z1AA','Z1AZ','Z2AA']::text[],
                    ARRAY['021','047','057','070','089','096']::text[],
                    ARRAY['SAM.gov Open Market', 'USACE MATOC', 'GSA Design-Build', 'IDIQ Task Orders']::text[],
                    ARRAY['Small Business']::text[],
                    ARRAY['Public trust eligible']::text[],
                    ARRAY['General construction', 'Design-build', 'Renovation', 'Site work', 'Electrical and mechanical subs']::text[],
                    ARRAY['021','047','096']::text[],
                    '{
                      "prime_contracts": 6,
                      "subcontracts": 3,
                      "recent_relevant_obligation": 9200000,
                      "strongest_domains": ["commercial_building", "site_work", "renovation", "facility_maintenance"],
                      "agency_relationships": {
                        "021": "Army and USACE small business renovation and task-order experience",
                        "047": "GSA building alteration and tenant improvement projects",
                        "096": "USACE civil/site work and facility repair past performance"
                      }
                    }'::jsonb,
                    '{
                      "target_blend_discount_to_calc_p75": 0.1,
                      "preferred_labor_mix": "working superintendent, estimator/PM, and vetted electrical/mechanical subcontractors"
                    }'::jsonb,
                    '{
                      "max_single_award_value": 15000000,
                      "avoid_no_incumbent_access": true,
                      "needs_prime_partner_above": 25000000
                    }'::jsonb
                  FROM tenant
                  CROSS JOIN entity
                  ON CONFLICT (tenant_id, company_name)
                  DO UPDATE SET
                    entity_id = EXCLUDED.entity_id,
                    target_naics_codes = EXCLUDED.target_naics_codes,
                    target_psc_codes = EXCLUDED.target_psc_codes,
                    target_agency_codes = EXCLUDED.target_agency_codes,
                    contract_vehicles = EXCLUDED.contract_vehicles,
                    set_aside_eligibilities = EXCLUDED.set_aside_eligibilities,
                    clearance_levels = EXCLUDED.clearance_levels,
                    socioeconomic_tags = EXCLUDED.socioeconomic_tags,
                    incumbent_agency_codes = EXCLUDED.incumbent_agency_codes,
                    past_performance_summary = EXCLUDED.past_performance_summary,
                    pricing_strategy = EXCLUDED.pricing_strategy,
                    risk_preferences = EXCLUDED.risk_preferences,
                    updated_at = now()
                  RETURNING customer_profile_id, tenant_id
                ),
                past_performance_rows AS (
                  SELECT *
                  FROM (
                    VALUES
                      ('CON-USACE-24-001', 'prime', NULL, 'Department of the Army', '021', '236220', 'Y1AA', 'Administrative Building Renovation', 'Interior renovation, ADA upgrades, finish replacement, and phased construction in an occupied federal building.', 1850000.00, ARRAY['USACE MATOC']::text[], 'Public trust eligible', 'Very Good'),
                      ('CON-GSA-23-018', 'prime', NULL, 'General Services Administration', '047', '238990', 'Z1AA', 'Federal Tenant Improvement Buildout', 'Tenant improvement buildout with demolition, drywall, electrical coordination, HVAC tie-ins, and closeout documentation.', 2420000.00, ARRAY['GSA Design-Build']::text[], 'Public trust eligible', 'Exceptional'),
                      ('CON-USACE-25-006', 'prime', NULL, 'U.S. Army Corps of Engineers', '096', '237990', 'Y1AZ', 'Civil Site and Drainage Improvements', 'Site grading, drainage structures, concrete flatwork, and utility coordination for a federal installation.', 3180000.00, ARRAY['SAM.gov Open Market']::text[], 'None', 'Very Good'),
                      ('CON-USAF-24-012', 'subcontractor', 'Regional Federal Builder JV', 'Department of the Air Force', '057', '238210', 'Z2AA', 'Facility Electrical Modernization Support', 'Electrical subcontract support, panel replacements, conduit, lighting, and commissioning support.', 1760000.00, ARRAY['Prime subcontract']::text[], 'Public trust eligible', 'Very Good')
                  ) AS rows(
                    contract_number, role, prime_name, agency_name, agency_code,
                    naics_code, psc_code, title, description, obligated_amount,
                    contract_vehicles, clearance_required, customer_rating
                  )
                ),
                upsert_past_performance AS (
                  INSERT INTO capture.customer_past_performance (
                    tenant_id, customer_profile_id, source, contract_number,
                    role, prime_name, agency_name, agency_code, naics_code,
                    psc_code, title, description, start_date, end_date,
                    obligated_amount, contract_vehicles, clearance_required,
                    customer_rating, source_payload
                  )
                  SELECT
                    profile.tenant_id,
                    profile.customer_profile_id,
                    'demo_customer_import',
                    rows.contract_number,
                    rows.role,
                    rows.prime_name,
                    rows.agency_name,
                    rows.agency_code,
                    rows.naics_code,
                    rows.psc_code,
                    rows.title,
                    rows.description,
                    DATE '2024-01-01',
                    DATE '2026-12-31',
                    rows.obligated_amount,
                    rows.contract_vehicles,
                    rows.clearance_required,
                    rows.customer_rating,
                    jsonb_build_object('demo_customer_profile', true, 'business_type', 'construction')
                  FROM profile
                  CROSS JOIN past_performance_rows rows
                  ON CONFLICT (tenant_id, contract_number, role)
                  DO UPDATE SET
                    customer_profile_id = EXCLUDED.customer_profile_id,
                    source = EXCLUDED.source,
                    prime_name = EXCLUDED.prime_name,
                    agency_name = EXCLUDED.agency_name,
                    agency_code = EXCLUDED.agency_code,
                    naics_code = EXCLUDED.naics_code,
                    psc_code = EXCLUDED.psc_code,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    obligated_amount = EXCLUDED.obligated_amount,
                    contract_vehicles = EXCLUDED.contract_vehicles,
                    clearance_required = EXCLUDED.clearance_required,
                    customer_rating = EXCLUDED.customer_rating,
                    source_payload = EXCLUDED.source_payload,
                    updated_at = now()
                  RETURNING past_performance_id
                ),
                upsert_billing AS (
                  INSERT INTO capture.billing_accounts (
                    tenant_id, billing_provider, provider_customer_id,
                    provider_subscription_id, subscription_status, price_id,
                    trial_ends_at, current_period_ends_at, billing_email,
                    source_payload
                  )
                  SELECT
                    tenant.tenant_id,
                    'manual',
                    'cus_demo_construction_business',
                    'sub_demo_construction_business',
                    'trialing',
                    'price_captureos_construction_demo',
                    now() + INTERVAL '30 days',
                    now() + INTERVAL '30 days',
                    'billing@constructionbusiness.example',
                    '{"demo_customer_profile": true}'::jsonb
                  FROM tenant
                  ON CONFLICT (tenant_id)
                  DO UPDATE SET
                    billing_provider = EXCLUDED.billing_provider,
                    provider_customer_id = EXCLUDED.provider_customer_id,
                    provider_subscription_id = EXCLUDED.provider_subscription_id,
                    subscription_status = EXCLUDED.subscription_status,
                    price_id = EXCLUDED.price_id,
                    trial_ends_at = EXCLUDED.trial_ends_at,
                    current_period_ends_at = EXCLUDED.current_period_ends_at,
                    billing_email = EXCLUDED.billing_email,
                    source_payload = EXCLUDED.source_payload,
                    updated_at = now()
                  RETURNING billing_account_id
                )
                SELECT
                  (SELECT count(*) FROM tenant)::int AS tenants,
                  (SELECT count(*) FROM profile)::int AS customer_profiles,
                  (SELECT count(*) FROM lead_user)::int + (SELECT count(*) FROM analyst_user)::int AS tenant_users,
                  (SELECT count(*) FROM upsert_past_performance)::int AS past_performance_rows,
                  (SELECT count(*) FROM upsert_billing)::int AS billing_accounts;
                """
            )
            construction_row = cur.fetchone()
    return {
        "tenants": int(metal_row[0]) + int(construction_row[0]),
        "customer_profiles": int(metal_row[1]) + int(construction_row[1]),
        "tenant_users": int(metal_row[2]) + int(construction_row[2]),
        "past_performance_rows": int(metal_row[3]) + int(construction_row[3]),
        "billing_accounts": int(metal_row[4]) + int(construction_row[4]),
    }
