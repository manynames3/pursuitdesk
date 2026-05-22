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

        upsert_entities(conn, entities)
        upsert_opportunities(conn, opportunities)
        upsert_awards(conn, awards)
        upsert_sub_awards(conn, sub_awards)
        upsert_calc_labor_rates(conn, labor_rates)

        return {
            "entities": len(entities),
            "opportunities": len(opportunities),
            "awards": len(awards),
            "sub_awards": len(sub_awards),
            "calc_labor_rates": len(labor_rates),
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
        subs = sub_patterns[domain]
        for tier_index, sub_name in enumerate(subs[:3], start=1):
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
