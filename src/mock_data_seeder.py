from __future__ import annotations

import argparse
import hashlib
import math
import os
import random
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import psycopg2
from psycopg2.extras import Json, execute_values


VECTOR_DIMENSION = 1536
NAMESPACE = uuid.UUID("4f4f97f4-c724-46c4-aa87-6d8c8c8b4f3c")
NOW = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)


def seed_mock_data(database_url: str, reset: bool = False) -> Dict[str, int]:
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        ensure_calc_labor_rates_table(conn)
        if reset:
            reset_capture_tables(conn)

        entities = build_entities()
        opportunities = build_opportunities()
        awards = build_awards(entities)
        sub_awards = build_sub_awards(awards, entities)
        labor_rates = build_calc_labor_rates()
        workspace = build_workspace_seed(entities, opportunities, awards, sub_awards, labor_rates)

        upsert_entities(conn, entities)
        upsert_opportunities(conn, opportunities)
        upsert_awards(conn, awards)
        upsert_sub_awards(conn, sub_awards)
        upsert_calc_labor_rates(conn, labor_rates)
        upsert_tenants(conn, workspace["tenants"])
        upsert_tenant_users(conn, workspace["tenant_users"])
        upsert_customer_profiles(conn, workspace["customer_profiles"])
        upsert_capture_workflows(conn, workspace["capture_workflows"])
        upsert_opportunity_notes(conn, workspace["opportunity_notes"])
        upsert_competitor_watchlist(conn, workspace["competitor_watchlist"])
        upsert_customer_past_performance(conn, workspace["customer_past_performance"])
        upsert_billing_accounts(conn, workspace["billing_accounts"])
        upsert_compliance_controls(conn, workspace["compliance_controls"])
        upsert_data_freshness(conn, workspace["data_freshness"])
        upsert_source_evidence(conn, workspace["source_evidence"])

        return {
            "entities": len(entities),
            "opportunities": len(opportunities),
            "awards": len(awards),
            "sub_awards": len(sub_awards),
            "calc_labor_rates": len(labor_rates),
            "tenants": len(workspace["tenants"]),
            "tenant_users": len(workspace["tenant_users"]),
            "customer_profiles": len(workspace["customer_profiles"]),
            "capture_workflows": len(workspace["capture_workflows"]),
            "opportunity_notes": len(workspace["opportunity_notes"]),
            "competitor_watchlist": len(workspace["competitor_watchlist"]),
            "customer_past_performance": len(workspace["customer_past_performance"]),
            "billing_accounts": len(workspace["billing_accounts"]),
            "compliance_controls": len(workspace["compliance_controls"]),
            "data_freshness": len(workspace["data_freshness"]),
            "source_evidence": len(workspace["source_evidence"]),
        }


def ensure_calc_labor_rates_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS capture.calc_labor_rates (
              labor_rate_id uuid PRIMARY KEY,
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
              source text NOT NULL DEFAULT 'CALC+ mock',
              source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
              source_updated_at timestamptz NOT NULL DEFAULT now(),
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              CHECK (naics_code IS NULL OR naics_code ~ '^[0-9]{2,6}$')
            );

            CREATE INDEX IF NOT EXISTS calc_labor_rates_category_idx
              ON capture.calc_labor_rates (normalized_labor_category);

            CREATE INDEX IF NOT EXISTS calc_labor_rates_naics_psc_idx
              ON capture.calc_labor_rates (naics_code, psc_code);

            CREATE INDEX IF NOT EXISTS calc_labor_rates_ceiling_idx
              ON capture.calc_labor_rates (ceiling_hourly_rate DESC);
            """
        )


def reset_capture_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE TABLE
              capture.audit_events,
              capture.billing_events,
              capture.ingest_runs,
              capture.customer_past_performance,
              capture.billing_accounts,
              capture.compliance_controls,
              capture.source_evidence,
              capture.opportunity_notes,
              capture.competitor_watchlist,
              capture.capture_opportunity_workflow,
              capture.customer_profiles,
              capture.tenant_users,
              capture.tenants,
              capture.data_freshness,
              capture.sub_awards,
              capture.awards,
              capture.opportunities,
              capture.entities,
              capture.calc_labor_rates
            RESTART IDENTITY CASCADE;
            """
        )


def build_entities() -> List[Dict[str, Any]]:
    specs = [
        ("lockheed", "Lockheed Martin Corporation", "VNDLOCKHEED1", "52088", [
            "Lockheed Martin Corp",
            "Lockheed Martin Tactical Systems",
            "Lockheed Martin Logistics",
            "Lockheed Martin Rotary and Mission Systems",
            "LMT RMS",
        ]),
        ("northrop", "Northrop Grumman Systems Corporation", "VNDNORTHRP01", "78022", [
            "Northrop Grumman Corp",
            "Northrop Grumman Mission Systems",
            "NGC Systems",
        ]),
        ("gd", "General Dynamics Information Technology, Inc.", "VNDGDIT00001", "07MU1", [
            "GDIT",
            "General Dynamics IT",
            "General Dynamics Mission Systems",
        ]),
        ("leidos", "Leidos, Inc.", "VNDLEIDOS001", "52326", ["Leidos Holdings", "Leidos Innovations", "Leidos Defense Group"]),
        ("booz", "Booz Allen Hamilton Inc.", "VNDBOOZALN01", "17038", ["Booz Allen", "BAH", "Booz Allen Hamilton Federal"]),
        ("saic", "Science Applications International Corporation", "VNDSAIC00001", "79343", ["SAIC", "SAIC Federal"]),
        ("caci", "CACI, Inc. - Federal", "VNDCACIFED01", "11057", ["CACI Federal", "CACI International"]),
        ("palantir", "Palantir USG, Inc.", "VNDPALANTIR1", "7GUD7", ["Palantir Technologies USG", "Palantir Government"]),
        ("accenture", "Accenture Federal Services LLC", "VNDACCENTR01", "4R7V9", ["AFS", "Accenture Federal"]),
        ("mantech", "ManTech Advanced Systems International, Inc.", "VNDMANTECH01", "0HD54", ["ManTech", "Mantech International"]),
        ("anduril", "Anduril Federal", "VNDANDURIL01", "8XWZ1", ["Anduril Industries Federal", "Anduril Defense"]),
        ("redhorse", "Redhorse Corporation", "VNDREDHORS01", "3Y1S2", ["Redhorse Federal", "Red Horse Corp"]),
        ("octo", "Octo Metric LLC", "VNDOCTO00001", "6YSP4", ["Octo Consulting", "Octo Federal"]),
        ("bigbear", "BigBear.ai Federal LLC", "VNDBIGBEAR01", "8ZXC2", ["BigBear.ai", "Big Bear Federal"]),
        ("raft", "Raft LLC", "VNDRAFT00001", "8EGQ1", ["Raft Federal", "Raft DevSecOps"]),
        ("riva", "RIVA Solutions, Inc.", "VNDRIVA00001", "5YEQ5", ["RIVA Federal", "Riva Solutions"]),
        ("trex", "T-Rex Solutions, LLC", "VNDTREX00001", "7XZH6", ["T-Rex", "T-Rex Federal"]),
        ("bluehalo", "BlueHalo, LLC", "VNDBLUEHAL01", "8V1H3", ["Blue Halo", "BlueHalo Federal"]),
        ("twosix", "Two Six Technologies, Inc.", "VNDTWOSIX001", "8JRL4", ["Two Six Labs", "Two Six Federal"]),
        ("govini", "Govini, Inc.", "VNDGOVINI001", "6J7K1", ["Govini Federal", "Govini Decision Science"]),
        ("metron", "Metron, Inc.", "VNDMETRON001", "0ME73", ["Metron Scientific", "Metron Federal"]),
    ]
    return [
        {
            "entity_id": stable_uuid(f"entity:{key}"),
            "legal_name": legal_name,
            "canonical_uei": uei,
            "cage_code": cage,
            "alias_names": aliases,
            "source_payload": {
                "mock_seed": True,
                "fragmented_vendor_strings": aliases,
                "seeded_at": NOW.isoformat(),
            },
        }
        for key, legal_name, uei, cage, aliases in specs
    ]


def build_opportunities() -> List[Dict[str, Any]]:
    specs = [
        {
            "key": "opp-c5isr-ai",
            "notice_id": "SAM-2026-C5ISR-AI-001",
            "solicitation_number": "W56KGY-26-R-0007",
            "title": "Army C5ISR AI Mission Data Fabric",
            "naics_code": "541715",
            "psc_code": "AC12",
            "agency": "Department of the Army",
            "agency_code": "021",
            "subtier": "Army Contracting Command",
            "office": "Aberdeen Proving Ground",
            "value": (Decimal("45000000.00"), Decimal("95000000.00")),
            "deadline": datetime(2026, 7, 10, 17, 0, tzinfo=timezone.utc),
            "domain": "c5isr_ai",
            "sow": "Program manager, data scientist, systems engineer, and cyber security engineer support for C5ISR data fusion, AI/ML model operations, tactical edge integration, and predictive analytics for mission command.",
        },
        {
            "key": "opp-logistics",
            "notice_id": "SAM-2026-DLA-LOG-002",
            "solicitation_number": "SP4701-26-R-1012",
            "title": "DLA Predictive Logistics Sustainment Analytics",
            "naics_code": "541614",
            "psc_code": "R706",
            "agency": "Defense Logistics Agency",
            "agency_code": "097",
            "subtier": "DLA Information Operations",
            "office": "DLA Contracting Services Office",
            "value": (Decimal("18000000.00"), Decimal("42000000.00")),
            "deadline": datetime(2026, 6, 28, 16, 0, tzinfo=timezone.utc),
            "domain": "logistics",
            "sow": "Logistics analyst, business analyst, program manager, and systems engineer services for supply chain risk scoring, sustainment forecasting, and operational dashboard modernization.",
        },
        {
            "key": "opp-cloud-cyber",
            "notice_id": "SAM-2026-USAF-ZT-003",
            "solicitation_number": "FA8773-26-R-0044",
            "title": "USAF Zero Trust Cloud Modernization",
            "naics_code": "541512",
            "psc_code": "DA01",
            "agency": "Department of the Air Force",
            "agency_code": "057",
            "subtier": "Air Force Materiel Command",
            "office": "Hanscom AFB",
            "value": (Decimal("65000000.00"), Decimal("140000000.00")),
            "deadline": datetime(2026, 8, 5, 15, 30, tzinfo=timezone.utc),
            "domain": "cloud_cyber",
            "sow": "Cloud architect, DevSecOps engineer, cyber security engineer, and program manager labor for zero trust architecture, AWS GovCloud migration, platform engineering, and continuous ATO.",
        },
        {
            "key": "opp-cyber-range",
            "notice_id": "SAM-2026-NAVY-CYBER-004",
            "solicitation_number": "N00039-26-R-2201",
            "title": "Navy Fleet Cyber Range Operations",
            "naics_code": "541519",
            "psc_code": "R425",
            "agency": "Department of the Navy",
            "agency_code": "017",
            "subtier": "Naval Information Warfare Systems Command",
            "office": "NIWC Pacific",
            "value": (Decimal("24000000.00"), Decimal("61000000.00")),
            "deadline": datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc),
            "domain": "cyber_range",
            "sow": "Cyber security engineer, systems engineer, and program manager support for fleet cyber range exercises, threat emulation, SOC integration, and training operations.",
        },
        {
            "key": "opp-case-mgmt",
            "notice_id": "SAM-2026-DHS-CASE-005",
            "solicitation_number": "70RTAC-26-R-0009",
            "title": "DHS Enterprise Case Management Modernization",
            "naics_code": "541511",
            "psc_code": "DA10",
            "agency": "Department of Homeland Security",
            "agency_code": "070",
            "subtier": "Office of Procurement Operations",
            "office": "DHS HQ",
            "value": (Decimal("30000000.00"), Decimal("80000000.00")),
            "deadline": datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc),
            "domain": "case_mgmt",
            "sow": "Business analyst, cloud architect, DevSecOps engineer, and program manager labor for low-code case management, data migration, records integration, and user-centered delivery.",
        },
    ]
    opportunities = []
    for spec in specs:
        value_min, value_max = spec["value"]
        opportunities.append(
            {
                "opportunity_id": stable_uuid(f"opportunity:{spec['key']}"),
                "notice_id": spec["notice_id"],
                "solicitation_number": spec["solicitation_number"],
                "title": spec["title"],
                "opportunity_type": "Solicitation",
                "base_type": "Solicitation",
                "active_status": "active",
                "posted_at": datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc),
                "response_deadline": spec["deadline"],
                "naics_code": spec["naics_code"],
                "psc_code": spec["psc_code"],
                "set_aside_code": None,
                "set_aside_description": None,
                "funding_agency_name": spec["agency"],
                "funding_agency_code": spec["agency_code"],
                "subtier_name": spec["subtier"],
                "office_name": spec["office"],
                "full_parent_path_name": f"{spec['agency']}.{spec['subtier']}.{spec['office']}",
                "full_parent_path_code": spec["agency_code"],
                "organization_type": "OFFICE",
                "place_of_performance": {"country": {"code": "USA"}, "state": {"code": "VA"}},
                "office_address": {"countryCode": "USA", "state": "VA"},
                "estimated_value_min": value_min,
                "estimated_value_max": value_max,
                "currency_code": "USD",
                "description_url": f"https://sam.gov/opp/{spec['notice_id']}/description",
                "ui_link": f"https://sam.gov/opp/{spec['notice_id']}/view",
                "resource_links": [f"https://sam.gov/opp/{spec['notice_id']}/attachments/sow.pdf"],
                "sow_text": spec["sow"],
                "sow_embedding": vector_literal(domain_vector(spec["domain"], f"{spec['key']}:sow", noise=0.035)),
                "source_payload": {"mock_seed": True, "personnel_requirements": spec["sow"]},
            }
        )
    return opportunities


def build_awards(entities: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    entity_ids = {entity["legal_name"]: entity["entity_id"] for entity in entities}
    specs = [
        ("c5isr_ai", "Lockheed Martin Corporation", "W56KGY21C0001", "Tactical AI Mission Command Integration", "541715", "AC12", "021", Decimal("88000000.00"), date(2025, 9, 28)),
        ("c5isr_ai", "Palantir USG, Inc.", "W56KGY22C0018", "Army Data Fabric Prototype Expansion", "541715", "AC12", "021", Decimal("52000000.00"), date(2025, 3, 17)),
        ("c5isr_ai", "Booz Allen Hamilton Inc.", "W56KGY23F0142", "C5ISR Decision Support Analytics", "541715", "AC12", "021", Decimal("36000000.00"), date(2024, 11, 6)),
        ("c5isr_ai", "Northrop Grumman Systems Corporation", "W56KGY20D9011", "Tactical Edge Sensor Fusion", "541715", "AC12", "021", Decimal("76000000.00"), date(2024, 5, 21)),
        ("logistics", "Leidos, Inc.", "SP470121F0044", "Predictive Supply Chain Analytics", "541614", "R706", "097", Decimal("41000000.00"), date(2025, 10, 1)),
        ("logistics", "Science Applications International Corporation", "SP470122C0009", "DLA Sustainment Forecasting Platform", "541614", "R706", "097", Decimal("29000000.00"), date(2024, 8, 15)),
        ("logistics", "General Dynamics Information Technology, Inc.", "SP470123F0021", "Inventory Risk Management Data Services", "541614", "R706", "097", Decimal("33000000.00"), date(2023, 12, 11)),
        ("cloud_cyber", "General Dynamics Information Technology, Inc.", "FA877321C0022", "Air Force Zero Trust Cloud Engineering", "541512", "DA01", "057", Decimal("118000000.00"), date(2025, 7, 1)),
        ("cloud_cyber", "Accenture Federal Services LLC", "FA877322F0093", "Enterprise Cloud Migration Factory", "541512", "DA01", "057", Decimal("97000000.00"), date(2024, 9, 23)),
        ("cloud_cyber", "CACI, Inc. - Federal", "FA877323C0051", "Continuous ATO and DevSecOps Platform", "541512", "DA01", "057", Decimal("68000000.00"), date(2024, 1, 19)),
        ("cyber_range", "ManTech Advanced Systems International, Inc.", "N0003922C0104", "Fleet Cyber Training Range Operations", "541519", "R425", "017", Decimal("54000000.00"), date(2025, 5, 30)),
        ("cyber_range", "Booz Allen Hamilton Inc.", "N0003923F3030", "Cyber Range Threat Emulation Support", "541519", "R425", "017", Decimal("45000000.00"), date(2024, 4, 12)),
        ("cyber_range", "Northrop Grumman Systems Corporation", "N0003921C2008", "Navy Mission Network Defense Exercises", "541519", "R425", "017", Decimal("63000000.00"), date(2023, 9, 7)),
        ("case_mgmt", "Accenture Federal Services LLC", "70RTAC22F0007", "DHS Case Management Platform Modernization", "541511", "DA10", "070", Decimal("74000000.00"), date(2025, 2, 14)),
        ("case_mgmt", "CACI, Inc. - Federal", "70RTAC23C0028", "Records and Case Workflow Integration", "541511", "DA10", "070", Decimal("39000000.00"), date(2024, 6, 24)),
        ("case_mgmt", "T-Rex Solutions, LLC", "70RTAC21F0401", "Enterprise Data Migration Services", "541511", "DA10", "070", Decimal("25000000.00"), date(2023, 3, 3)),
    ]
    awards: List[Dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        domain, prime_name, piid, title, naics, psc, agency_code, value, signed = spec
        award_id = stable_uuid(f"award:{piid}")
        awards.append(
            {
                "award_id": award_id,
                "contract_award_unique_key": f"CONT_AWD_{piid}_9700_-NONE-_-NONE-",
                "piid": piid,
                "referenced_idv_piid": None,
                "parent_award_id": None,
                "opportunity_id": None,
                "prime_entity_id": entity_ids[prime_name],
                "award_number": piid,
                "award_type": "Definitive Contract" if index % 3 else "Delivery/Task Order",
                "title": title,
                "description": f"{title}: program management, technical labor, analytics delivery, and mission integration services.",
                "signed_date": signed,
                "period_of_performance_start": signed,
                "period_of_performance_end": date(signed.year + 4, signed.month, min(signed.day, 28)),
                "awarding_agency_name": agency_name(agency_code),
                "awarding_agency_code": agency_code,
                "funding_agency_name": agency_name(agency_code),
                "funding_agency_code": agency_code,
                "contracting_office_name": "Mock Federal Contracting Office",
                "contracting_office_code": f"{agency_code}X",
                "naics_code": naics,
                "psc_code": psc,
                "set_aside_code": None,
                "total_obligation": value,
                "current_total_value": value,
                "potential_total_value": value * Decimal("1.25"),
                "description_embedding": vector_literal(domain_vector(domain, f"{piid}:award", noise=0.055)),
                "source_payload": {
                    "mock_seed": True,
                    "raw_prime_vendor_string": raw_prime_variant(prime_name, index),
                    "domain": domain,
                },
            }
        )
    return awards


def build_sub_awards(awards: Sequence[Mapping[str, Any]], entities: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    entity_ids = {entity["legal_name"]: entity["entity_id"] for entity in entities}
    sub_patterns = {
        "c5isr_ai": ["Anduril Federal", "BigBear.ai Federal LLC", "Two Six Technologies, Inc.", "Metron, Inc."],
        "logistics": ["Redhorse Corporation", "Govini, Inc.", "RIVA Solutions, Inc.", "Octo Metric LLC"],
        "cloud_cyber": ["Raft LLC", "RIVA Solutions, Inc.", "Octo Metric LLC", "BlueHalo, LLC"],
        "cyber_range": ["BlueHalo, LLC", "Two Six Technologies, Inc.", "Anduril Federal", "Metron, Inc."],
        "case_mgmt": ["T-Rex Solutions, LLC", "RIVA Solutions, Inc.", "Octo Metric LLC", "Raft LLC"],
    }
    sub_awards: List[Dict[str, Any]] = []
    for award in awards:
        domain = award["source_payload"]["domain"]
        subs = [
            sub_name
            for sub_name in sub_patterns[domain]
            if entity_ids[sub_name] != award["prime_entity_id"]
        ][:3]
        for tier_index, sub_name in enumerate(subs, start=1):
            sub_awards.append(
                {
                    "sub_award_id": stable_uuid(f"subaward:{award['piid']}:{sub_name}"),
                    "fsrs_report_id": f"FSRS-{award['piid']}-{tier_index}",
                    "award_id": award["award_id"],
                    "prime_entity_id": award["prime_entity_id"],
                    "subcontractor_entity_id": entity_ids[sub_name],
                    "parent_sub_award_id": None,
                    "relationship_path": [],
                    "tier": 1,
                    "subaward_number": f"{award['piid']}-SUB-{tier_index:02d}",
                    "action_date": date(award["signed_date"].year, min(12, award["signed_date"].month + 1), 15),
                    "amount": (award["total_obligation"] * Decimal(str(0.045 + 0.02 * tier_index))).quantize(Decimal("0.01")),
                    "description": f"{sub_name} support for {award['title']}",
                    "naics_code": award["naics_code"],
                    "psc_code": award["psc_code"],
                    "source_payload": {
                        "mock_seed": True,
                        "raw_subcontractor_vendor_string": raw_sub_variant(sub_name, tier_index),
                    },
                }
            )
    return sub_awards


def build_calc_labor_rates() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    categories = [
        ("program manager", "Program Manager", "Bachelor's", 10, Decimal("182.50"), Decimal("132.40"), Decimal("158.25")),
        ("cloud architect", "Cloud Architect", "Bachelor's", 8, Decimal("205.00"), Decimal("151.75"), Decimal("177.90")),
        ("cyber security engineer", "Cyber Security Engineer", "Bachelor's", 7, Decimal("196.75"), Decimal("145.10"), Decimal("169.60")),
        ("data scientist", "Data Scientist", "Master's", 6, Decimal("214.25"), Decimal("156.00"), Decimal("183.40")),
        ("devsecops engineer", "DevSecOps Engineer", "Bachelor's", 6, Decimal("188.40"), Decimal("139.50"), Decimal("163.20")),
        ("systems engineer", "Systems Engineer", "Bachelor's", 8, Decimal("176.90"), Decimal("128.25"), Decimal("151.30")),
        ("logistics analyst", "Logistics Analyst", "Bachelor's", 5, Decimal("142.60"), Decimal("101.80"), Decimal("121.45")),
        ("business analyst", "Business Analyst", "Bachelor's", 5, Decimal("137.20"), Decimal("98.75"), Decimal("116.80")),
    ]
    naics_psc = [
        ("541715", "AC12"),
        ("541614", "R706"),
        ("541512", "DA01"),
        ("541519", "R425"),
        ("541511", "DA10"),
    ]
    for normalized, label, education, years, ceiling, p50, p75 in categories:
        for naics, psc in naics_psc:
            multiplier = Decimal("1.08") if psc in {"AC12", "DA01"} and normalized in {"data scientist", "cloud architect", "cyber security engineer"} else Decimal("1.00")
            rows.append(
                {
                    "labor_rate_id": stable_uuid(f"rate:{normalized}:{naics}:{psc}"),
                    "labor_category": label,
                    "normalized_labor_category": normalized,
                    "education_level": education,
                    "min_years_experience": years,
                    "site": "CONUS",
                    "schedule": "GSA MAS IT Professional Services",
                    "naics_code": naics,
                    "psc_code": psc,
                    "ceiling_hourly_rate": (ceiling * multiplier).quantize(Decimal("0.01")),
                    "percentile_50_hourly_rate": (p50 * multiplier).quantize(Decimal("0.01")),
                    "percentile_75_hourly_rate": (p75 * multiplier).quantize(Decimal("0.01")),
                    "source": "CALC+ synthetic benchmark",
                    "source_updated_at": NOW,
                }
            )
    return rows


def build_workspace_seed(
    entities: Sequence[Mapping[str, Any]],
    opportunities: Sequence[Mapping[str, Any]],
    awards: Sequence[Mapping[str, Any]],
    sub_awards: Sequence[Mapping[str, Any]],
    labor_rates: Sequence[Mapping[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    entity_ids = {entity["legal_name"]: entity["entity_id"] for entity in entities}
    opportunity_ids = {opp["notice_id"]: opp["opportunity_id"] for opp in opportunities}
    tenant_id = stable_uuid("tenant:demo-growth")
    capture_lead_id = stable_uuid("tenant-user:demo-growth:capture.lead@example.com")
    analyst_id = stable_uuid("tenant-user:demo-growth:analyst@example.com")

    tenants = [
        {
            "tenant_id": tenant_id,
            "tenant_slug": "demo-growth",
            "tenant_name": "Apex Analytica Federal Growth Team",
            "plan_tier": "enterprise",
            "data_region": "us-east-1",
        }
    ]
    tenant_users = [
        {
            "user_id": capture_lead_id,
            "tenant_id": tenant_id,
            "email": "capture.lead@example.com",
            "display_name": "Capture Lead",
            "role": "capture_manager",
            "status": "active",
            "last_seen_at": NOW,
        },
        {
            "user_id": analyst_id,
            "tenant_id": tenant_id,
            "email": "analyst@example.com",
            "display_name": "Market Analyst",
            "role": "analyst",
            "status": "active",
            "last_seen_at": NOW,
        },
    ]
    customer_profiles = [
        {
            "customer_profile_id": stable_uuid("customer-profile:demo-growth:raft"),
            "tenant_id": tenant_id,
            "entity_id": entity_ids["Raft LLC"],
            "company_name": "Apex Analytica Federal Growth Team",
            "target_naics_codes": ["541512", "541511", "541715"],
            "target_psc_codes": ["DA01", "DA10", "AC12", "R425"],
            "target_agency_codes": ["057", "070", "021"],
            "contract_vehicles": ["GSA MAS IT", "OASIS+", "CIO-SP4 Teaming Pool"],
            "set_aside_eligibilities": ["Small Business", "8(a) Mentor-Protege"],
            "clearance_levels": ["Secret", "TS/SCI eligible"],
            "socioeconomic_tags": ["Small Business", "Agile DevSecOps", "Cloud Native"],
            "incumbent_agency_codes": ["057", "070"],
            "past_performance_summary": {
                "prime_contracts": 1,
                "subcontracts": 9,
                "recent_relevant_obligation": 56400000,
                "strongest_domains": ["cloud_cyber", "case_mgmt", "c5isr_ai"],
                "agency_relationships": {
                    "057": "active subcontractor on zero trust and platform engineering programs",
                    "070": "case management modernization delivery partner",
                    "021": "emerging C5ISR tactical data partner",
                },
            },
            "pricing_strategy": {
                "target_blend_discount_to_calc_p75": 0.08,
                "preferred_labor_mix": "senior architecture with mid-level delivery bench",
            },
            "risk_preferences": {
                "max_single_award_value": 150000000,
                "avoid_no_incumbent_access": False,
                "needs_prime_partner_above": 60000000,
            },
        }
    ]
    workflow_specs = {
        "SAM-2026-C5ISR-AI-001": ("qualifying", "go", "high", "Gate 2: Teaming", "Two Six and Anduril are likely differentiators for tactical edge credibility."),
        "SAM-2026-DLA-LOG-002": ("tracking", "undecided", "medium", "Gate 1: Fit", "Needs stronger logistics past performance before bid decision."),
        "SAM-2026-USAF-ZT-003": ("bid", "go", "high", "Gate 3: Solution", "Excellent cloud and DevSecOps fit; validate incumbent access."),
        "SAM-2026-NAVY-CYBER-004": ("tracking", "undecided", "medium", "Gate 1: Fit", "Cyber range work is attractive but requires exercise operations partner."),
        "SAM-2026-DHS-CASE-005": ("qualifying", "go", "high", "Gate 2: Teaming", "Strong DHS case management and migration adjacency."),
    }
    capture_workflows = []
    opportunity_notes = []
    for index, (notice_id, spec) in enumerate(workflow_specs.items(), start=1):
        status, decision, priority, stage, rationale = spec
        opportunity_id = opportunity_ids[notice_id]
        capture_workflows.append(
            {
                "workflow_id": stable_uuid(f"workflow:{tenant_id}:{notice_id}"),
                "tenant_id": tenant_id,
                "opportunity_id": opportunity_id,
                "owner_user_id": capture_lead_id if priority == "high" else analyst_id,
                "status": status,
                "go_no_go": decision,
                "priority": priority,
                "stage": stage,
                "next_review_at": datetime(2026, 5, min(28, 22 + index), 15, 0, tzinfo=timezone.utc),
                "due_at": next(opp["response_deadline"] for opp in opportunities if opp["notice_id"] == notice_id),
                "tags": ["priority-review", "customer-fit"] if priority == "high" else ["monitor"],
                "notes": rationale,
                "decision_rationale": rationale,
            }
        )
        opportunity_notes.append(
            {
                "note_id": stable_uuid(f"note:{tenant_id}:{notice_id}:initial"),
                "tenant_id": tenant_id,
                "opportunity_id": opportunity_id,
                "author_user_id": capture_lead_id,
                "note_type": "capture_note",
                "body": rationale,
                "created_at": NOW,
            }
        )

    competitor_watchlist = [
        {
            "watchlist_id": stable_uuid(f"watchlist:{tenant_id}:lockheed"),
            "tenant_id": tenant_id,
            "entity_id": entity_ids["Lockheed Martin Corporation"],
            "reason": "Repeated Army C5ISR wins with sensor fusion and tactical AI adjacency.",
            "priority": "high",
        },
        {
            "watchlist_id": stable_uuid(f"watchlist:{tenant_id}:gdit"),
            "tenant_id": tenant_id,
            "entity_id": entity_ids["General Dynamics Information Technology, Inc."],
            "reason": "Air Force cloud incumbent with major zero trust obligation base.",
            "priority": "high",
        },
        {
            "watchlist_id": stable_uuid(f"watchlist:{tenant_id}:accenture"),
            "tenant_id": tenant_id,
            "entity_id": entity_ids["Accenture Federal Services LLC"],
            "reason": "DHS and cloud modernization competitor with broad delivery bench.",
            "priority": "medium",
        },
    ]
    customer_past_performance = build_customer_past_performance(tenant_id, customer_profiles[0]["customer_profile_id"])
    billing_accounts = [
        {
            "billing_account_id": stable_uuid(f"billing:{tenant_id}"),
            "tenant_id": tenant_id,
            "billing_provider": "stripe",
            "provider_customer_id": "cus_demo_captureos",
            "provider_subscription_id": "sub_demo_captureos",
            "subscription_status": "trialing",
            "price_id": "price_captureos_growth_demo",
            "trial_ends_at": datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc),
            "current_period_ends_at": datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc),
            "billing_email": "billing@example.com",
            "source_payload": {"mock_seed": True},
        }
    ]
    compliance_controls = build_compliance_controls()
    data_freshness = [
        freshness_row("SAM.gov", "Opportunities", "https://api.sam.gov/opportunities/v2/search", len(opportunities), 6),
        freshness_row("USAspending", "Contract Awards", "https://api.usaspending.gov/api/v2/search/spending_by_award/", len(awards), 24),
        freshness_row("FSRS", "Subaward Reporting", "https://www.fsrs.gov/", len(sub_awards), 24),
        freshness_row("SAM.gov", "Entity Management and Exclusions", "https://sam.gov/entity-information", len(entities), 24),
        freshness_row("GSA CALC+", "Labor Rate Benchmarks", "https://buy.gsa.gov/pricing/", len(labor_rates), 24),
    ]
    source_evidence = build_source_evidence(opportunities, awards, sub_awards, labor_rates, entities)
    return {
        "tenants": tenants,
        "tenant_users": tenant_users,
        "customer_profiles": customer_profiles,
        "capture_workflows": capture_workflows,
        "opportunity_notes": opportunity_notes,
        "competitor_watchlist": competitor_watchlist,
        "customer_past_performance": customer_past_performance,
        "billing_accounts": billing_accounts,
        "compliance_controls": compliance_controls,
        "data_freshness": data_freshness,
        "source_evidence": source_evidence,
    }


def build_customer_past_performance(tenant_id: str, customer_profile_id: str) -> List[Dict[str, Any]]:
    rows = [
        ("RAF-FA8773-24-F-0112", "subcontractor", "General Dynamics Information Technology, Inc.", "Department of the Air Force", "057", "541512", "DA01", "Zero Trust Platform Engineering", Decimal("18400000.00"), ["GSA MAS IT"], "Secret"),
        ("RAF-70RTAC-23-F-0029", "subcontractor", "Accenture Federal Services LLC", "Department of Homeland Security", "070", "541511", "DA10", "Case Management Data Migration", Decimal("15100000.00"), ["OASIS+"], "Public Trust"),
        ("RAF-W56KGY-25-F-0041", "subcontractor", "Palantir USG, Inc.", "Department of the Army", "021", "541715", "AC12", "Mission Data Fabric DevSecOps", Decimal("22900000.00"), ["CIO-SP4 Teaming Pool"], "TS/SCI eligible"),
        ("RAF-N00039-24-F-0099", "subcontractor", "Booz Allen Hamilton Inc.", "Department of the Navy", "017", "541519", "R425", "Cyber Range Automation Support", Decimal("9600000.00"), ["GSA MAS IT"], "Secret"),
    ]
    return [
        {
            "past_performance_id": stable_uuid(f"past-performance:{contract_number}"),
            "tenant_id": tenant_id,
            "customer_profile_id": customer_profile_id,
            "source": "mock_customer_import",
            "contract_number": contract_number,
            "role": role,
            "prime_name": prime_name,
            "agency_name": agency_name_value,
            "agency_code": agency_code,
            "naics_code": naics_code,
            "psc_code": psc_code,
            "title": title,
            "description": f"{title} delivery with agile engineering, cleared staff, and production operations support.",
            "start_date": date(2024, 1, 1),
            "end_date": date(2026, 12, 31),
            "obligated_amount": amount,
            "contract_vehicles": vehicles,
            "clearance_required": clearance,
            "customer_rating": "Exceptional",
            "source_payload": {"mock_seed": True},
        }
        for contract_number, role, prime_name, agency_name_value, agency_code, naics_code, psc_code, title, amount, vehicles, clearance in rows
    ]


def build_compliance_controls() -> List[Dict[str, Any]]:
    specs = [
        ("auth.jwt", "Access Control", "JWT issuer, audience, and JWKS validation", "implemented", "FastAPI validates Bearer tokens when AUTH_REQUIRED=true; API Gateway JWT authorizer can also be enabled."),
        ("tenant.isolation", "Access Control", "Tenant-scoped data access", "implemented", "Tenant context is resolved from JWT claims or demo headers and applied to workflow, notes, billing, and onboarding queries."),
        ("audit.workflow", "Audit", "Workflow mutation audit trail", "implemented", "Go/no-go and workflow updates write audit_events with actor, resource, IP, user agent, and payload metadata."),
        ("secrets.gsa", "Secrets", "GSA API key outside source control", "implemented", "Ingest Lambda reads SAM_API_KEY_SECRET_ARN from Secrets Manager or environment for local-only use."),
        ("privacy.headers", "Privacy", "Browser security headers", "implemented", "Cloudflare Pages serves X-Frame-Options, no-sniff, referrer, permissions, and CSP headers."),
        ("billing.stripe", "Billing", "Stripe checkout and webhook ledger", "implemented", "API creates Stripe Checkout sessions when STRIPE_API_KEY and STRIPE_PRICE_ID are configured; webhook events are persisted."),
    ]
    return [
        {
            "control_id": stable_uuid(f"control:{key}"),
            "control_key": key,
            "control_family": family,
            "control_name": name,
            "implementation_status": status,
            "implementation_notes": notes,
            "evidence_url": None,
            "owner": "platform",
        }
        for key, family, name, status, notes in specs
    ]


def freshness_row(source_system: str, dataset_name: str, source_url: str, record_count: int, sla_hours: int) -> Dict[str, Any]:
    return {
        "freshness_id": stable_uuid(f"freshness:{source_system}:{dataset_name}"),
        "source_system": source_system,
        "dataset_name": dataset_name,
        "source_mode": "mock_seed",
        "last_successful_sync_at": NOW,
        "last_attempted_sync_at": NOW,
        "sync_status": "ready",
        "record_count": record_count,
        "freshness_sla_hours": sla_hours,
        "source_url": source_url,
        "notes": "Synthetic demo seed. Replace with live ingestion watermark when API keys are enabled.",
    }


def build_source_evidence(
    opportunities: Sequence[Mapping[str, Any]],
    awards: Sequence[Mapping[str, Any]],
    sub_awards: Sequence[Mapping[str, Any]],
    labor_rates: Sequence[Mapping[str, Any]],
    entities: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    entity_lookup = {entity["entity_id"]: entity for entity in entities}
    award_lookup = {award["award_id"]: award for award in awards}
    evidence: List[Dict[str, Any]] = []
    for opp in opportunities:
        evidence.append(
            {
                "evidence_id": stable_uuid(f"evidence:opportunity:{opp['notice_id']}"),
                "opportunity_id": opp["opportunity_id"],
                "award_id": None,
                "sub_award_id": None,
                "labor_rate_id": None,
                "related_entity_id": None,
                "evidence_type": "opportunity",
                "source_system": "SAM.gov Opportunities API",
                "source_record_id": opp["notice_id"],
                "source_title": opp["title"],
                "source_url": opp["ui_link"],
                "source_record_date": opp["posted_at"].date(),
                "source_amount": opp["estimated_value_max"],
                "agency_name": opp["funding_agency_name"],
                "agency_code": opp["funding_agency_code"],
                "naics_code": opp["naics_code"],
                "psc_code": opp["psc_code"],
                "explanation": "Active solicitation source used for title, agency, NAICS/PSC, deadline, value range, and SOW semantic matching.",
                "confidence": Decimal("1.0000"),
                "source_payload": {"resource_links": opp["resource_links"], "description_url": opp["description_url"]},
            }
        )
    for award in awards:
        prime = entity_lookup[award["prime_entity_id"]]
        evidence.append(
            {
                "evidence_id": stable_uuid(f"evidence:award:{award['piid']}"),
                "opportunity_id": None,
                "award_id": award["award_id"],
                "sub_award_id": None,
                "labor_rate_id": None,
                "related_entity_id": award["prime_entity_id"],
                "evidence_type": "award",
                "source_system": "USAspending Contract Awards API",
                "source_record_id": award["piid"],
                "source_title": f"{prime['legal_name']} won {award['title']}",
                "source_url": f"https://www.usaspending.gov/search/?keywords={award['piid']}",
                "source_record_date": award["signed_date"],
                "source_amount": award["total_obligation"],
                "agency_name": award["funding_agency_name"],
                "agency_code": award["funding_agency_code"],
                "naics_code": award["naics_code"],
                "psc_code": award["psc_code"],
                "explanation": "Historical prime award used to establish competitor win frequency, agency fit, obligation baseline, and semantic similarity.",
                "confidence": Decimal("0.9600"),
                "source_payload": {"raw_prime_vendor_string": award["source_payload"]["raw_prime_vendor_string"]},
            }
        )
    for sub_award in sub_awards:
        award = award_lookup[sub_award["award_id"]]
        sub = entity_lookup[sub_award["subcontractor_entity_id"]]
        prime = entity_lookup[sub_award["prime_entity_id"]]
        evidence.append(
            {
                "evidence_id": stable_uuid(f"evidence:subaward:{sub_award['subaward_number']}"),
                "opportunity_id": None,
                "award_id": sub_award["award_id"],
                "sub_award_id": sub_award["sub_award_id"],
                "labor_rate_id": None,
                "related_entity_id": sub_award["subcontractor_entity_id"],
                "evidence_type": "subaward",
                "source_system": "FSRS Subaward Reporting API",
                "source_record_id": sub_award["subaward_number"],
                "source_title": f"{sub['legal_name']} supported {prime['legal_name']} on {award['piid']}",
                "source_url": "https://www.fsrs.gov/",
                "source_record_date": sub_award["action_date"],
                "source_amount": sub_award["amount"],
                "agency_name": award["funding_agency_name"],
                "agency_code": award["funding_agency_code"],
                "naics_code": sub_award["naics_code"],
                "psc_code": sub_award["psc_code"],
                "explanation": "Subaward record used to infer proven teaming links and subcontractor partner depth.",
                "confidence": Decimal("0.9400"),
                "source_payload": {"fsrs_report_id": sub_award["fsrs_report_id"]},
            }
        )
    for rate in labor_rates:
        evidence.append(
            {
                "evidence_id": stable_uuid(f"evidence:labor-rate:{rate['labor_rate_id']}"),
                "opportunity_id": None,
                "award_id": None,
                "sub_award_id": None,
                "labor_rate_id": rate["labor_rate_id"],
                "related_entity_id": None,
                "evidence_type": "labor_rate",
                "source_system": "GSA CALC+ Pricing API",
                "source_record_id": str(rate["labor_rate_id"]),
                "source_title": f"{rate['labor_category']} ceiling benchmark",
                "source_url": "https://buy.gsa.gov/pricing/",
                "source_record_date": rate["source_updated_at"].date(),
                "source_amount": rate["ceiling_hourly_rate"],
                "agency_name": None,
                "agency_code": None,
                "naics_code": rate["naics_code"],
                "psc_code": rate["psc_code"],
                "explanation": "Labor ceiling benchmark used to compare solicitation labor categories against price-to-win rate pressure.",
                "confidence": Decimal("0.9300"),
                "source_payload": {"schedule": rate["schedule"], "site": rate["site"]},
            }
        )
    return evidence


def upsert_entities(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["entity_id"],
            row["legal_name"],
            row["canonical_uei"],
            row["cage_code"],
            row["alias_names"],
            Json(row["source_payload"]),
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.entities (
              entity_id, legal_name, canonical_uei, cage_code, alias_names, source_payload
            )
            VALUES %s
            ON CONFLICT (entity_id)
            DO UPDATE SET
              legal_name = EXCLUDED.legal_name,
              canonical_uei = EXCLUDED.canonical_uei,
              cage_code = EXCLUDED.cage_code,
              alias_names = EXCLUDED.alias_names,
              source_payload = capture.entities.source_payload || EXCLUDED.source_payload,
              updated_at = now();
            """,
            values,
            page_size=100,
        )


def upsert_opportunities(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["opportunity_id"],
            row["notice_id"],
            row["solicitation_number"],
            row["title"],
            row["opportunity_type"],
            row["base_type"],
            row["active_status"],
            row["posted_at"],
            row["response_deadline"],
            row["naics_code"],
            row["psc_code"],
            row["set_aside_code"],
            row["set_aside_description"],
            row["funding_agency_name"],
            row["funding_agency_code"],
            row["subtier_name"],
            row["office_name"],
            row["full_parent_path_name"],
            row["full_parent_path_code"],
            row["organization_type"],
            Json(row["place_of_performance"]),
            Json(row["office_address"]),
            row["estimated_value_min"],
            row["estimated_value_max"],
            row["currency_code"],
            row["description_url"],
            row["ui_link"],
            row["resource_links"],
            row["sow_text"],
            row["sow_embedding"],
            Json(row["source_payload"]),
            NOW,
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.opportunities (
              opportunity_id, notice_id, solicitation_number, title, opportunity_type, base_type,
              active_status, posted_at, response_deadline, naics_code, psc_code, set_aside_code,
              set_aside_description, funding_agency_name, funding_agency_code, subtier_name, office_name,
              full_parent_path_name, full_parent_path_code, organization_type, place_of_performance,
              office_address, estimated_value_min, estimated_value_max, currency_code, description_url,
              ui_link, resource_links, sow_text, sow_embedding, source_payload, source_updated_at
            )
            VALUES %s
            ON CONFLICT (notice_id)
            DO UPDATE SET
              solicitation_number = EXCLUDED.solicitation_number,
              title = EXCLUDED.title,
              active_status = EXCLUDED.active_status,
              response_deadline = EXCLUDED.response_deadline,
              estimated_value_min = EXCLUDED.estimated_value_min,
              estimated_value_max = EXCLUDED.estimated_value_max,
              sow_text = EXCLUDED.sow_text,
              sow_embedding = EXCLUDED.sow_embedding,
              source_payload = capture.opportunities.source_payload || EXCLUDED.source_payload,
              updated_at = now();
            """,
            values,
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)",
            page_size=50,
        )


def upsert_awards(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["award_id"],
            row["contract_award_unique_key"],
            row["piid"],
            row["referenced_idv_piid"],
            row["parent_award_id"],
            row["opportunity_id"],
            row["prime_entity_id"],
            row["award_number"],
            row["award_type"],
            row["title"],
            row["description"],
            row["signed_date"],
            row["period_of_performance_start"],
            row["period_of_performance_end"],
            row["awarding_agency_name"],
            row["awarding_agency_code"],
            row["funding_agency_name"],
            row["funding_agency_code"],
            row["contracting_office_name"],
            row["contracting_office_code"],
            row["naics_code"],
            row["psc_code"],
            row["set_aside_code"],
            row["total_obligation"],
            row["current_total_value"],
            row["potential_total_value"],
            row["description_embedding"],
            Json(row["source_payload"]),
            NOW,
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.awards (
              award_id, contract_award_unique_key, piid, referenced_idv_piid, parent_award_id,
              opportunity_id, prime_entity_id, award_number, award_type, title, description,
              signed_date, period_of_performance_start, period_of_performance_end, awarding_agency_name,
              awarding_agency_code, funding_agency_name, funding_agency_code, contracting_office_name,
              contracting_office_code, naics_code, psc_code, set_aside_code, total_obligation,
              current_total_value, potential_total_value, description_embedding, source_payload, source_updated_at
            )
            VALUES %s
            ON CONFLICT (contract_award_unique_key)
            DO UPDATE SET
              prime_entity_id = EXCLUDED.prime_entity_id,
              title = EXCLUDED.title,
              description = EXCLUDED.description,
              total_obligation = EXCLUDED.total_obligation,
              current_total_value = EXCLUDED.current_total_value,
              potential_total_value = EXCLUDED.potential_total_value,
              description_embedding = EXCLUDED.description_embedding,
              source_payload = capture.awards.source_payload || EXCLUDED.source_payload,
              updated_at = now();
            """,
            values,
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)",
            page_size=50,
        )


def upsert_sub_awards(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["sub_award_id"],
            row["fsrs_report_id"],
            row["award_id"],
            row["prime_entity_id"],
            row["subcontractor_entity_id"],
            row["parent_sub_award_id"],
            row["relationship_path"],
            row["tier"],
            row["subaward_number"],
            row["action_date"],
            row["amount"],
            row["description"],
            row["naics_code"],
            row["psc_code"],
            Json(row["source_payload"]),
            NOW,
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.sub_awards (
              sub_award_id, fsrs_report_id, award_id, prime_entity_id, subcontractor_entity_id,
              parent_sub_award_id, relationship_path, tier, subaward_number, action_date, amount,
              description, naics_code, psc_code, source_payload, source_updated_at
            )
            VALUES %s
            ON CONFLICT (sub_award_id)
            DO UPDATE SET
              fsrs_report_id = EXCLUDED.fsrs_report_id,
              amount = EXCLUDED.amount,
              description = EXCLUDED.description,
              source_payload = capture.sub_awards.source_payload || EXCLUDED.source_payload,
              updated_at = now();
            """,
            values,
            page_size=100,
        )


def upsert_calc_labor_rates(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["labor_rate_id"],
            row["labor_category"],
            row["normalized_labor_category"],
            row["education_level"],
            row["min_years_experience"],
            row["site"],
            row["schedule"],
            row["naics_code"],
            row["psc_code"],
            row["ceiling_hourly_rate"],
            row["percentile_50_hourly_rate"],
            row["percentile_75_hourly_rate"],
            row["source"],
            row["source_updated_at"],
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.calc_labor_rates (
              labor_rate_id, labor_category, normalized_labor_category, education_level,
              min_years_experience, site, schedule, naics_code, psc_code, ceiling_hourly_rate,
              percentile_50_hourly_rate, percentile_75_hourly_rate, source, source_updated_at
            )
            VALUES %s
            ON CONFLICT (labor_rate_id)
            DO UPDATE SET
              ceiling_hourly_rate = EXCLUDED.ceiling_hourly_rate,
              percentile_50_hourly_rate = EXCLUDED.percentile_50_hourly_rate,
              percentile_75_hourly_rate = EXCLUDED.percentile_75_hourly_rate,
              source_updated_at = EXCLUDED.source_updated_at,
              updated_at = now();
            """,
            values,
            page_size=100,
        )


def upsert_tenants(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (row["tenant_id"], row["tenant_slug"], row["tenant_name"], row["plan_tier"], row["data_region"])
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.tenants (tenant_id, tenant_slug, tenant_name, plan_tier, data_region)
            VALUES %s
            ON CONFLICT (tenant_slug)
            DO UPDATE SET
              tenant_name = EXCLUDED.tenant_name,
              plan_tier = EXCLUDED.plan_tier,
              data_region = EXCLUDED.data_region,
              updated_at = now();
            """,
            values,
            page_size=50,
        )


def upsert_tenant_users(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["user_id"],
            row["tenant_id"],
            row["email"],
            row["display_name"],
            row["role"],
            row["status"],
            row["last_seen_at"],
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.tenant_users (
              user_id, tenant_id, email, display_name, role, status, last_seen_at
            )
            VALUES %s
            ON CONFLICT (tenant_id, (lower(email)))
            DO UPDATE SET
              display_name = EXCLUDED.display_name,
              role = EXCLUDED.role,
              status = EXCLUDED.status,
              last_seen_at = EXCLUDED.last_seen_at,
              updated_at = now();
            """,
            values,
            page_size=50,
        )


def upsert_customer_profiles(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["customer_profile_id"],
            row["tenant_id"],
            row["entity_id"],
            row["company_name"],
            row["target_naics_codes"],
            row["target_psc_codes"],
            row["target_agency_codes"],
            row["contract_vehicles"],
            row["set_aside_eligibilities"],
            row["clearance_levels"],
            row["socioeconomic_tags"],
            row["incumbent_agency_codes"],
            Json(row["past_performance_summary"]),
            Json(row["pricing_strategy"]),
            Json(row["risk_preferences"]),
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.customer_profiles (
              customer_profile_id, tenant_id, entity_id, company_name, target_naics_codes,
              target_psc_codes, target_agency_codes, contract_vehicles, set_aside_eligibilities,
              clearance_levels, socioeconomic_tags, incumbent_agency_codes, past_performance_summary,
              pricing_strategy, risk_preferences
            )
            VALUES %s
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
              updated_at = now();
            """,
            values,
            page_size=20,
        )


def upsert_capture_workflows(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["workflow_id"],
            row["tenant_id"],
            row["opportunity_id"],
            row["owner_user_id"],
            row["status"],
            row["go_no_go"],
            row["priority"],
            row["stage"],
            row["next_review_at"],
            row["due_at"],
            row["tags"],
            row["notes"],
            row["decision_rationale"],
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.capture_opportunity_workflow (
              workflow_id, tenant_id, opportunity_id, owner_user_id, status, go_no_go,
              priority, stage, next_review_at, due_at, tags, notes, decision_rationale
            )
            VALUES %s
            ON CONFLICT (tenant_id, opportunity_id)
            DO UPDATE SET
              owner_user_id = EXCLUDED.owner_user_id,
              status = EXCLUDED.status,
              go_no_go = EXCLUDED.go_no_go,
              priority = EXCLUDED.priority,
              stage = EXCLUDED.stage,
              next_review_at = EXCLUDED.next_review_at,
              due_at = EXCLUDED.due_at,
              tags = EXCLUDED.tags,
              notes = EXCLUDED.notes,
              decision_rationale = EXCLUDED.decision_rationale,
              updated_at = now();
            """,
            values,
            page_size=50,
        )


def upsert_opportunity_notes(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["note_id"],
            row["tenant_id"],
            row["opportunity_id"],
            row["author_user_id"],
            row["note_type"],
            row["body"],
            row["created_at"],
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.opportunity_notes (
              note_id, tenant_id, opportunity_id, author_user_id, note_type, body, created_at
            )
            VALUES %s
            ON CONFLICT (note_id)
            DO UPDATE SET
              body = EXCLUDED.body;
            """,
            values,
            page_size=50,
        )


def upsert_competitor_watchlist(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (row["watchlist_id"], row["tenant_id"], row["entity_id"], row["reason"], row["priority"])
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.competitor_watchlist (
              watchlist_id, tenant_id, entity_id, reason, priority
            )
            VALUES %s
            ON CONFLICT (tenant_id, entity_id)
            DO UPDATE SET
              reason = EXCLUDED.reason,
              priority = EXCLUDED.priority,
              updated_at = now();
            """,
            values,
            page_size=50,
        )


def upsert_customer_past_performance(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["past_performance_id"],
            row["tenant_id"],
            row["customer_profile_id"],
            row["source"],
            row["contract_number"],
            row["role"],
            row["prime_name"],
            row["agency_name"],
            row["agency_code"],
            row["naics_code"],
            row["psc_code"],
            row["title"],
            row["description"],
            row["start_date"],
            row["end_date"],
            row["obligated_amount"],
            row["contract_vehicles"],
            row["clearance_required"],
            row["customer_rating"],
            Json(row["source_payload"]),
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.customer_past_performance (
              past_performance_id, tenant_id, customer_profile_id, source, contract_number,
              role, prime_name, agency_name, agency_code, naics_code, psc_code, title,
              description, start_date, end_date, obligated_amount, contract_vehicles,
              clearance_required, customer_rating, source_payload
            )
            VALUES %s
            ON CONFLICT (tenant_id, contract_number, role)
            DO UPDATE SET
              prime_name = EXCLUDED.prime_name,
              agency_name = EXCLUDED.agency_name,
              agency_code = EXCLUDED.agency_code,
              naics_code = EXCLUDED.naics_code,
              psc_code = EXCLUDED.psc_code,
              title = EXCLUDED.title,
              description = EXCLUDED.description,
              obligated_amount = EXCLUDED.obligated_amount,
              contract_vehicles = EXCLUDED.contract_vehicles,
              clearance_required = EXCLUDED.clearance_required,
              customer_rating = EXCLUDED.customer_rating,
              source_payload = EXCLUDED.source_payload,
              updated_at = now();
            """,
            values,
            page_size=50,
        )


def upsert_billing_accounts(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["billing_account_id"],
            row["tenant_id"],
            row["billing_provider"],
            row["provider_customer_id"],
            row["provider_subscription_id"],
            row["subscription_status"],
            row["price_id"],
            row["trial_ends_at"],
            row["current_period_ends_at"],
            row["billing_email"],
            Json(row["source_payload"]),
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.billing_accounts (
              billing_account_id, tenant_id, billing_provider, provider_customer_id,
              provider_subscription_id, subscription_status, price_id, trial_ends_at,
              current_period_ends_at, billing_email, source_payload
            )
            VALUES %s
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
              updated_at = now();
            """,
            values,
            page_size=20,
        )


def upsert_compliance_controls(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["control_id"],
            row["control_key"],
            row["control_family"],
            row["control_name"],
            row["implementation_status"],
            row["implementation_notes"],
            row["evidence_url"],
            row["owner"],
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.compliance_controls (
              control_id, control_key, control_family, control_name,
              implementation_status, implementation_notes, evidence_url, owner
            )
            VALUES %s
            ON CONFLICT (control_key)
            DO UPDATE SET
              control_family = EXCLUDED.control_family,
              control_name = EXCLUDED.control_name,
              implementation_status = EXCLUDED.implementation_status,
              implementation_notes = EXCLUDED.implementation_notes,
              evidence_url = EXCLUDED.evidence_url,
              owner = EXCLUDED.owner,
              updated_at = now();
            """,
            values,
            page_size=20,
        )


def upsert_data_freshness(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["freshness_id"],
            row["source_system"],
            row["dataset_name"],
            row["source_mode"],
            row["last_successful_sync_at"],
            row["last_attempted_sync_at"],
            row["sync_status"],
            row["record_count"],
            row["freshness_sla_hours"],
            row["source_url"],
            row["notes"],
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.data_freshness (
              freshness_id, source_system, dataset_name, source_mode, last_successful_sync_at,
              last_attempted_sync_at, sync_status, record_count, freshness_sla_hours, source_url, notes
            )
            VALUES %s
            ON CONFLICT (source_system, dataset_name)
            DO UPDATE SET
              source_mode = EXCLUDED.source_mode,
              last_successful_sync_at = EXCLUDED.last_successful_sync_at,
              last_attempted_sync_at = EXCLUDED.last_attempted_sync_at,
              sync_status = EXCLUDED.sync_status,
              record_count = EXCLUDED.record_count,
              freshness_sla_hours = EXCLUDED.freshness_sla_hours,
              source_url = EXCLUDED.source_url,
              notes = EXCLUDED.notes,
              updated_at = now();
            """,
            values,
            page_size=20,
        )


def upsert_source_evidence(conn, rows: Sequence[Mapping[str, Any]]) -> None:
    values = [
        (
            row["evidence_id"],
            row["opportunity_id"],
            row["award_id"],
            row["sub_award_id"],
            row["labor_rate_id"],
            row["related_entity_id"],
            row["evidence_type"],
            row["source_system"],
            row["source_record_id"],
            row["source_title"],
            row["source_url"],
            row["source_record_date"],
            row["source_amount"],
            row["agency_name"],
            row["agency_code"],
            row["naics_code"],
            row["psc_code"],
            row["explanation"],
            row["confidence"],
            Json(row["source_payload"]),
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO capture.source_evidence (
              evidence_id, opportunity_id, award_id, sub_award_id, labor_rate_id,
              related_entity_id, evidence_type, source_system, source_record_id,
              source_title, source_url, source_record_date, source_amount, agency_name,
              agency_code, naics_code, psc_code, explanation, confidence, source_payload
            )
            VALUES %s
            ON CONFLICT (evidence_id)
            DO UPDATE SET
              source_title = EXCLUDED.source_title,
              source_url = EXCLUDED.source_url,
              source_amount = EXCLUDED.source_amount,
              explanation = EXCLUDED.explanation,
              confidence = EXCLUDED.confidence,
              source_payload = EXCLUDED.source_payload,
              updated_at = now();
            """,
            values,
            page_size=200,
        )


def stable_uuid(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def domain_vector(domain: str, salt: str, noise: float) -> List[float]:
    base = raw_vector(f"domain:{domain}")
    rng = random.Random(int(hashlib.sha256(salt.encode("utf-8")).hexdigest()[:16], 16))
    noisy = [component + rng.gauss(0.0, noise) for component in base]
    return normalize(noisy)


def raw_vector(seed: str) -> List[float]:
    rng = random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16))
    return normalize([rng.gauss(0.0, 1.0) for _ in range(VECTOR_DIMENSION)])


def normalize(values: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def agency_name(code: str) -> str:
    return {
        "017": "Department of the Navy",
        "021": "Department of the Army",
        "057": "Department of the Air Force",
        "070": "Department of Homeland Security",
        "097": "Defense Logistics Agency",
    }[code]


def raw_prime_variant(prime_name: str, index: int) -> str:
    variants = {
        "Lockheed Martin Corporation": ["Lockheed Martin Tactical Systems", "Lockheed Martin Corp"],
        "Northrop Grumman Systems Corporation": ["Northrop Grumman Mission Systems", "NGC Systems"],
        "General Dynamics Information Technology, Inc.": ["GDIT", "General Dynamics IT"],
        "Leidos, Inc.": ["Leidos Defense Group", "Leidos Innovations"],
        "Booz Allen Hamilton Inc.": ["Booz Allen", "BAH"],
        "Accenture Federal Services LLC": ["AFS", "Accenture Federal"],
        "CACI, Inc. - Federal": ["CACI Federal", "CACI International"],
        "ManTech Advanced Systems International, Inc.": ["ManTech", "Mantech International"],
        "Palantir USG, Inc.": ["Palantir Government", "Palantir Technologies USG"],
        "Science Applications International Corporation": ["SAIC", "SAIC Federal"],
        "T-Rex Solutions, LLC": ["T-Rex", "T-Rex Federal"],
    }
    choices = variants.get(prime_name, [prime_name])
    return choices[index % len(choices)]


def raw_sub_variant(sub_name: str, index: int) -> str:
    replacements = {
        "BigBear.ai Federal LLC": ["BigBear.ai", "Big Bear Federal"],
        "Two Six Technologies, Inc.": ["Two Six Labs", "Two Six Federal"],
        "RIVA Solutions, Inc.": ["Riva Solutions", "RIVA Federal"],
        "Octo Metric LLC": ["Octo Consulting", "Octo Federal"],
        "Raft LLC": ["Raft DevSecOps", "Raft Federal"],
    }
    choices = replacements.get(sub_name, [sub_name])
    return choices[index % len(choices)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed GovCon CaptureOS with deterministic high-fidelity mock data.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="PostgreSQL DSN. Defaults to DATABASE_URL.")
    parser.add_argument("--reset", action="store_true", help="Truncate seeded CaptureOS tables before inserting.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("Provide --database-url or set DATABASE_URL.")
    counts = seed_mock_data(args.database_url, reset=args.reset)
    print("Seeded GovCon CaptureOS mock data:")
    for table_name, count in counts.items():
        print(f"  {table_name}: {count}")


if __name__ == "__main__":
    main()
