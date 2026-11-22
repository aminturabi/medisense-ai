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

    def test_decimal_drop_potassium_no_false_emergency(self):
        # OCR reads Potassium 6.9 fine (real emergency), but 69 means the
        # decimal point was dropped - flag a check, never an emergency.
        r = analyze("Potassium 69 mmol/L")
        self.assertFalse(r["emergency"])
        self.assertEqual(r["lab_results"][0]["status"], "suspect_decimal")
        self.assertTrue(r["lab_results"][0]["suspect_decimal"])
        self.assertTrue(any(a["type"] == "decimal_check" for a in r["alerts"]))

    def test_decimal_drop_hba1c_and_creatinine(self):
        r = analyze("HbA1c 55 %")
        self.assertEqual(r["lab_results"][0]["status"], "suspect_decimal")
        r2 = analyze("Creatinine 90 mg/dL")
        self.assertEqual(r2["lab_results"][0]["status"], "suspect_decimal")
        self.assertFalse(r2["emergency"])

    def test_real_panic_still_fires(self):
        r = analyze("Potassium 6.9 mmol/L")
        self.assertTrue(r["emergency"])

    def test_pii_hidden_tokens_and_international_formats(self):
        out = redact_pii("Call +91 63972 28160 or 6397228160, CNIC 35202-1234567-1, mobile 0300-1234567")
        self.assertIn("[PHONE HIDDEN]", out)
        self.assertIn("[CNIC HIDDEN]", out)
        self.assertNotIn("63972", out)
        self.assertNotIn("35202", out)

    def test_empty_input_is_safe(self):
        r = analyze("hello world, no medical data here")
        self.assertEqual(r["medications"], [])
        self.assertEqual(r["lab_results"], [])
        self.assertFalse(r["emergency"])


if __name__ == "__main__":
    unittest.main()


URINE_OCR = """Shahid Farooq Hospital Lab. Clinical Laboratory Report
URINE COMPLETE EXAMINATION REPORT
Color Yellow
Turbidity Present
Deposit Seen
Sp. Gravity 1.020
pH 6.5
Glucose Nil
Protein Nil
Ketone Nil
Urobilinogen Normal
Bilirubin Nil
Blood Nil
Leucocytes +++
Pus Cells 20-22
Epithelial Cell JHPF Nil
RBC 02-03
Crystals Nil
Casts JHPF Nil
Bacteria [HPF Nil"""


class TestUrineReportGuard(unittest.TestCase):
    """Urine microscopy values are per-field counts, NOT blood counts.
    Regression: live test 2026-11-13 - 'RBC 02-03' fired a false
    DANGER emergency (blood RBC 2 million/uL) on a urine report."""

    def test_urine_rbc_range_is_not_blood_rbc(self):
        r = analyze(URINE_OCR)
        self.assertEqual(r["lab_results"], [])
        self.assertFalse(r["emergency"])

    def test_plain_blood_rbc_still_parses(self):
        r = analyze("RBC 5.1 million/uL\nHemoglobin 13.5 g/dL")
        names = {l["name"] for l in r["lab_results"]}
        self.assertTrue(any("RBC" in n for n in names))
        self.assertTrue(any("Hemoglobin" in n for n in names))

    def test_no_match_still_gives_an_answer(self):
        r = analyze(URINE_OCR)
        en = " ".join(r["explanations"]["en"])
        self.assertIn("could not find any blood test or medicine", en)
        self.assertEqual(en.count("does not replace your doctor"), 1)
        em = analyze("Hemoglobin 6.4 g/dL\nPotassium 6.9 mmol/L")
        self.assertNotIn("could not find", " ".join(em["explanations"]["en"]))


HOTI_PAGE1 = """HOTI MEDICAL LABORATORY
Pat: Name : M/O Amin
Sex : Female
Specimen Date : 22-Nov-26
Report Date : 11/22/2026 6:55 PM
Test Result Unit Normal Range
RA Factor Negative Iu/ml Up to 8
S, Uric Acid 5.0 Mg/dl 2.5-----7.0
C Reactive Protien
Test Result
CRP Negative"""

HOTI_PAGE2 = """HOTI MEDICAL LABORATORY
Pat: Name : M/O Amin
Sex : Female
Specimen Date : 22-Nov-26
Report Date : 11/22/2026 6:51 PM
Complete Blood Picture
Test Result Unit Normal Range
T.L.C 9,400 / cmm 4,000 - 11,000
Red Count 4.44 mil / mm3 3.80 - 5.80
Hemoglobin 11.7 g / dl Male: 14-----18 Female 12----16
Platelets Count 3,90,000 /cmm 1,50,000 - 4,50,000
Differential Leucocytes Count
Lymphocytes 34 % 20------50
Monocytes 04 % 03------10
Neutrophils 61 % 40------70
Eosinophils 01 % 0 ------6"""


class TestRealWorldHotiReport(unittest.TestCase):
    """Real report regression - Hoti Medical Laboratory, Mardan,
    22-Nov-2026 (patient M/O Amin, Female). This exact report failed
    completely before the real-world parser fix."""

    def test_all_eleven_tests_found(self):
        r = analyze(HOTI_PAGE1 + "\n" + HOTI_PAGE2)
        self.assertEqual(len(r["lab_results"]), 11)
        names = {l["name"] for l in r["lab_results"]}
        for expected in ("Hemoglobin", "WBC (White Blood Cells)", "Platelets",
                         "RBC (Red Blood Cells)", "Uric Acid", "Neutrophils",
                         "Lymphocytes", "Monocytes", "Eosinophils",
                         "RA Factor", "CRP (C Reactive Protein)"):
            self.assertIn(expected, names)

    def test_hoti_statuses_and_values(self):
        r = analyze(HOTI_PAGE1 + "\n" + HOTI_PAGE2)
        by_name = {l["name"]: l for l in r["lab_results"]}
        self.assertEqual(by_name["WBC (White Blood Cells)"]["value"], 9400)
        self.assertEqual(by_name["RBC (Red Blood Cells)"]["value"], 4.44)
        self.assertEqual(by_name["Platelets"]["value"], 390000)  # 3,90,000 Indian commas
        self.assertEqual(by_name["Uric Acid"]["value"], 5.0)
        self.assertEqual(by_name["Lymphocytes"]["value"], 34)
        self.assertEqual(by_name["Monocytes"]["value"], 4)   # printed as 04
        self.assertEqual(by_name["Neutrophils"]["value"], 61)
        self.assertEqual(by_name["Eosinophils"]["value"], 1)  # printed as 01
        self.assertEqual(by_name["RA Factor"]["value"], "Negative")
        self.assertEqual(by_name["CRP (C Reactive Protein)"]["value"], "Negative")
        # Everything normal except Hemoglobin, which is Low (11.7 < 12)
        for name, lab in by_name.items():
            expected = "low" if name == "Hemoglobin" else "normal"
            self.assertEqual(lab["status"], expected, name)
        self.assertEqual(by_name["Hemoglobin"]["value"], 11.7)

    def test_hoti_no_emergency_and_no_fake_medicine(self):
        r = analyze(HOTI_PAGE1 + "\n" + HOTI_PAGE2)
        self.assertFalse(r["emergency"])
        self.assertEqual(r["alerts"], [])
        # "Uric Acid 5.0 Mg/dl" must not become a medicine called "Acid"
        self.assertEqual(r["medications"], [])
        self.assertEqual(r["unverified_items"], [])

    def test_hoti_explanations_in_all_languages(self):
        r = analyze(HOTI_PAGE1 + "\n" + HOTI_PAGE2)
        for lang in ("en", "ur", "ps"):
            blob = " ".join(r["explanations"][lang])
            self.assertIn("RA Factor", blob)
            self.assertIn("CRP", blob)
            self.assertNotIn("URGENT", blob)

    def test_positive_qualitative_is_abnormal_not_emergency(self):
        r = analyze("CRP Positive\nRA Factor Positive")
        by_name = {l["name"]: l for l in r["lab_results"]}
        self.assertEqual(by_name["CRP (C Reactive Protein)"]["status"], "high")
        self.assertEqual(by_name["RA Factor"]["status"], "high")
        self.assertFalse(r["emergency"])
        self.assertIn("Positive", " ".join(r["explanations"]["en"]))

    def test_basophils_parse(self):
        r = analyze("Basophils 01 %")
        self.assertEqual(r["lab_results"][0]["name"], "Basophils")
        self.assertEqual(r["lab_results"][0]["value"], 1)
        self.assertEqual(r["lab_results"][0]["status"], "normal")
