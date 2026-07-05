import unittest

from src import api_v1_endpoints as api


class PWinScoringTests(unittest.TestCase):
    def test_pipeline_pwin_is_low_confidence_range(self):
        estimate = api._pipeline_pwin_estimate({
            "dashboard_relevance_score": 0.95,
            "opportunity_type": "Solicitation",
        })

        self.assertLessEqual(estimate["estimated_p_win"], 0.24)
        self.assertEqual(estimate["p_win_display_mode"], "p_win_range")
        self.assertLessEqual(estimate["p_win_range"]["high"], 0.24)
        self.assertRegex(estimate["p_win_range"]["label"], r"^\d+-\d+%$")

    def test_market_research_displays_capture_fit(self):
        estimate = api._pipeline_pwin_estimate({
            "dashboard_relevance_score": 0.95,
            "title": "Request for Information for cloud services",
        })

        self.assertEqual(estimate["p_win_display_mode"], "capture_fit")
        self.assertLessEqual(estimate["estimated_p_win"], 0.16)
        self.assertLessEqual(estimate["p_win_range"]["high"], 0.16)

    def test_structural_only_baseline_is_capped_and_explained(self):
        baseline = api._normalize_pwin_baseline(
            {
                "estimated_p_win": 0.48,
                "confidence": "low",
                "historical_match_count": 0,
                "model_scope": "structural_only",
            },
            {"estimated_p_win": 0.18},
            {"opportunity_type": "Solicitation"},
        )

        self.assertEqual(baseline["estimated_p_win_raw"], 0.48)
        self.assertEqual(baseline["estimated_p_win"], 0.24)
        self.assertLessEqual(baseline["p_win_range"]["high"], 0.24)
        self.assertIn("lacks historical/embedding-backed competitor evidence", " ".join(baseline["notes"]))

    def test_medium_confidence_baseline_shrinks_toward_market(self):
        baseline = api._normalize_pwin_baseline(
            {
                "estimated_p_win": 0.40,
                "confidence": "medium",
                "historical_match_count": 20,
                "model_scope": "historical",
            },
            {"estimated_p_win": 0.18},
            {"opportunity_type": "Solicitation"},
        )

        self.assertAlmostEqual(baseline["estimated_p_win"], 0.301, places=3)
        self.assertEqual(baseline["p_win_display_mode"], "p_win_range")
        self.assertLessEqual(baseline["p_win_range"]["high"], 0.35)
        self.assertIn("confidence-adjusted toward the market baseline", " ".join(baseline["notes"]))

    def test_high_confidence_above_fifty_requires_strong_inputs(self):
        baseline = api._normalize_pwin_baseline(
            {
                "estimated_p_win": 0.62,
                "confidence": "high",
                "historical_match_count": 100,
                "model_scope": "historical",
                "score_inputs": {
                    "our_relevance_signal": 0.86,
                    "partner_depth_score": 0.70,
                },
            },
            {"estimated_p_win": 0.25},
            {"opportunity_type": "Solicitation"},
        )

        self.assertGreater(baseline["estimated_p_win"], 0.50)
        self.assertLessEqual(baseline["estimated_p_win"], 0.58)
        self.assertLessEqual(baseline["p_win_range"]["high"], 0.58)


if __name__ == "__main__":
    unittest.main()
