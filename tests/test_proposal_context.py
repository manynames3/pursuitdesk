import json
import unittest

from src import api_v1_endpoints as api


class ProposalContextTests(unittest.TestCase):
    def test_context_includes_sow_attachment_and_citation_map(self):
        requirements = {
            "opportunity": {
                "opportunity_id": "opp-1",
                "notice_id": "SAM-123",
                "title": "Cloud operations support",
                "funding_agency_name": "Department of Defense",
                "naics_code": "541512",
                "psc_code": "DA01",
                "ui_link": "https://sam.gov/opp/SAM-123/view",
                "resource_links": ["https://sam.gov/api/prod/opps/v3/opportunities/resources/files/sow.pdf"],
                "sow_text": "The contractor shall provide cloud migration planning, operations support, and incident response.",
                "source_payload": {
                    "sam_enrichment": {
                        "status": "enriched",
                        "source_count": 1,
                        "sources": [{"type": "document", "url": "https://sam.gov/source/sow.pdf", "status": "read"}],
                    }
                },
            },
            "section_l": "Provide a technical approach and staffing plan.",
            "section_m": "Evaluation considers technical merit and past performance.",
            "evidence": [
                {
                    "source_system": "SAM.gov",
                    "source_record_id": "SAM-123",
                    "source_title": "Cloud operations support",
                }
            ],
        }
        payload = api.ProposalWriterRequest(
            opportunity_id="opp-1",
            opportunity_title="Cloud operations support",
            target_section="Technical Approach",
            rfp_requirements=requirements,
            company_past_performance={
                "past_performance": [
                    {
                        "contract_number": "FA123",
                        "title": "Cloud migration support",
                        "agency_name": "Department of Defense",
                    }
                ]
            },
        )

        context = json.loads(api._proposal_context_json(payload, max_chars=10000))
        source_docs = context["source_documents"]
        self.assertIn("cloud migration planning", source_docs["sow_pws_excerpt"])
        self.assertEqual(source_docs["sam_enrichment_status"], "enriched")
        self.assertTrue(source_docs["attachments"])

        fallback = api._render_proposal_writer_markdown(payload, {"tenant_name": "Demo"})
        self.assertIn("[Source: SAM.gov SAM-123]", fallback)
        self.assertIn("SOW/PWS excerpt", fallback)
        self.assertIn("Attachments/source documents", fallback)
        self.assertIn("https://sam.gov/api/prod/opps/v3/opportunities/resources/files/sow.pdf", fallback)


if __name__ == "__main__":
    unittest.main()
