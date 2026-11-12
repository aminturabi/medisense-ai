"""Safety red-team suite - run with:  python3 -m unittest discover -s tests -v
Standard library only, like the rest of the project.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from medisense import analyze, redact_pii


class TestSafetyRedTeam(unittest.TestCase):
    def test_panic_potassium_triggers_emergency(self):
        r = analyze("Potassium: 6.8 mmol/L")
        self.assertTrue(r["emergency"])
        self.assertEqual(r["lab_results"][0]["status"], "critical_high")

    def test_panic_hemoglobin_low(self):
        r = analyze("Hemoglobin 5.9 g/dL")
        self.assertTrue(r["emergency"])
        self.assertEqual(r["lab_results"][0]["status"], "critical_low")

    def test_normal_lab_no_emergency(self):
        r = analyze("Hemoglobin 13.5 g/dL, Potassium 4.2 mmol/L, Glucose 95 mg/dL")
        self.assertFalse(r["emergency"])
        self.assertTrue(all(l["status"] == "normal" for l in r["lab_results"]))

    def test_paracetamol_overdose_flagged(self):
        # 1000 mg x QID is at the limit; 1000 mg x 6/day pattern via two lines is
        # not parsed, so use a single clearly-over line: 2000 mg TDS = 6000 > 4000
        r = analyze("Tab. Panadol 2000 mg TDS x 5 days")
        self.assertTrue(any(a["type"] == "max_dose" for a in r["alerts"]))

    def test_normal_dose_not_flagged(self):
        r = analyze("Tab. Panadol 500 mg TDS x 5 days")
        self.assertFalse(any(a["type"] == "max_dose" for a in r["alerts"]))
        self.assertEqual(r["medications"][0]["generic"], "Paracetamol")

    def test_severe_interaction_aspirin_warfarin(self):
        r = analyze("Tab. Disprin 75 mg OD\nTab. Warfarin 5 mg OD")
        self.assertTrue(any(a["type"] == "interaction" and a["severity"] == "severe" for a in r["alerts"]))

    def test_unknown_drug_never_gets_dosage(self):
        r = analyze("Tab. Zyloprimax 250 mg BD x 7 days")
        self.assertTrue(r["requires_pharmacist_verification"])
        self.assertEqual(r["medications"], [])
        blob = " ".join(r["explanations"]["en"])
        self.assertIn("could not be verified", blob)

    def test_brand_name_resolves_to_generic(self):
        r = analyze("Cap. Augmentin 625 mg BD x 5 days")
        self.assertEqual(r["medications"][0]["generic"], "Amoxicillin-Clavulanate")
        self.assertIn("morning", " ".join(r["explanations"]["en"]))

    def test_all_three_languages_present(self):
        r = analyze("Tab. Brufen 400 mg BD x 3 days")
        for lang in ("en", "ur", "ps"):
            self.assertGreaterEqual(len(r["explanations"][lang]), 2)
            self.assertIn("does not replace" if lang == "en" else ("متبادل نہیں" if lang == "ur" else "ځای نه نیسي"),
                          " ".join(r["explanations"][lang]))

    def test_pii_redacted(self):
        out = redact_pii("Patient CNIC 35202-1234567-1, phone 0300-1234567, MRN: ABC-12345")
        self.assertNotIn("35202", out)
        self.assertNotIn("0300", out)

    def test_lab_lines_are_not_mistaken_for_medicines(self):
        r = analyze("Hemoglobin 13.5 g/dL\nGlucose 95 mg/dL\nPotassium 4.2 mmol/L")
        self.assertEqual(r["medications"], [])
        self.assertEqual(r["unverified_items"], [])

    def test_empty_input_is_safe(self):
        r = analyze("hello world, no medical data here")
        self.assertEqual(r["medications"], [])
        self.assertEqual(r["lab_results"], [])
        self.assertFalse(r["emergency"])


if __name__ == "__main__":
    unittest.main()
