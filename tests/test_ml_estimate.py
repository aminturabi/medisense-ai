"""ML estimate suite - run with:  python3 -m unittest discover -s tests -v
The NHANES-trained HbA1c estimate must appear ONLY when it should:
no HbA1c in the report, enough other results, and no emergency.
It must never alter the rule-based lab results.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from medisense import analyze

FULL_PANEL = (
    "Hemoglobin 13.2 g/dL\nWBC 8500 /uL\nPlatelets 230000 /uL\nRBC 4.6 million/uL\n"
    "Lymphocytes 30 %\nMonocytes 6 %\nNeutrophils 60 %\nEosinophils 2 %\nBasophils 0.5 %\n"
    "Glucose 182 mg/dL\nUrea 22 mg/dL\nCreatinine 0.9 mg/dL\nPotassium 4.3 mmol/L\n"
    "Sodium 139 mmol/L\nCalcium 9.4 mg/dL\nBilirubin 0.7 mg/dL\nUric Acid 5.4 mg/dL\n"
    "Cholesterol 210 mg/dL"
)


class TestMlEstimate(unittest.TestCase):
    def test_estimate_appears_without_hba1c(self):
        r = analyze(FULL_PANEL)
        ml = r["ml_estimate"]
        self.assertIsNotNone(ml)
        self.assertIn(ml["predicted_class"], ("Normal", "Prediabetes", "Diabetes range"))
        self.assertAlmostEqual(sum(ml["probabilities"].values()), 100.0, delta=0.5)
        self.assertGreaterEqual(ml["features_used"], 8)
        self.assertTrue(any("AI estimate" in line for line in r["explanations"]["en"]))

    def test_no_estimate_when_hba1c_present(self):
        r = analyze(FULL_PANEL + "\nHbA1c 6.1 %")
        self.assertIsNone(r["ml_estimate"])
        self.assertFalse(any("AI estimate" in line for line in r["explanations"]["en"]))

    def test_no_estimate_during_emergency(self):
        r = analyze(FULL_PANEL.replace("Potassium 4.3", "Potassium 6.9"))
        self.assertTrue(r["emergency"])
        self.assertIsNone(r["ml_estimate"])

    def test_no_estimate_with_too_few_results(self):
        r = analyze("Hemoglobin 13.5 g/dL")
        self.assertIsNone(r["ml_estimate"])

    def test_estimate_never_changes_rule_results(self):
        r = analyze(FULL_PANEL)
        glucose = [l for l in r["lab_results"] if l["name"].startswith("Glucose")][0]
        self.assertEqual(glucose["status"], "high")  # 182 > 140 by the rule range
        self.assertEqual(glucose["value"], 182.0)


if __name__ == "__main__":
    unittest.main()
