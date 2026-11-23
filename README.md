# MediSense AI - Prescription & Lab-Report Translator

A web app that explains a prescription or lab report in simple words, in
**English, Urdu and Pashto**, with audio - built for low-literacy patients
in Pakistan.

**No pip installs. No API keys. No heavy models.** The whole thing runs on
the Python standard library plus the browser's own built-in features.

## Run it (30 seconds)

```bash
python3 server.py
# open http://localhost:8000
```

Or just open `web/index.html` in a browser - the page carries a JavaScript
copy of the same engine, so it also works as a static site (Vercel,
Netlify, GitHub Pages, Hugging Face static Space). When served by
`server.py` it uses the Python API (`POST /api/analyze`), otherwise it
falls back to the JS engine automatically. Both engines are tested.

## What it does

1. **Photo or text in** - upload a photo (blur check first: Laplacian
   sharpness below 100 is rejected with "take it again"; printed text is
   read on-device with Tesseract.js), paste the text, or use a built-in
   sample. Two sample images are in `samples/`.
2. **PII scrubbed first** - CNIC, mobile numbers and MRNs are hidden
   before any processing.
3. **Deterministic safety checks - before any explanation is written:**
   - Lab values vs normal and **critical panic ranges**
     (e.g. Potassium > 6.0, Hemoglobin < 7.0, Glucose > 400) → red
     emergency banner: go to hospital / call Rescue 1122.
   - Medicine names matched (brand → generic, e.g. Panadol →
     Paracetamol) against `data/drugs_pakistan.csv`.
   - **Max daily dose check:** strength × frequency (OD/BD/TDS/QID)
     vs the listed maximum.
   - **Drug-drug interaction check** for every pair on the prescription.
   - Anything that cannot be matched is flagged
     `requires_pharmacist_verification` and gets **no dosage text at
     all** - just "confirm with your doctor or pharmacist".
4. **Simple explanation out** - fixed templates filled only from the
   verified tables above (no free-generating LLM, so it cannot invent a
   dose or a side effect). Because the sentences are templates, the Urdu
   and Pashto versions are human-written templates too, not machine
   guesses. Dose times are shown as icons (🌅 ☀️ 🌙).
5. **Listen button** - the browser reads the explanation aloud
   (ur-PK / ps-AF / en-US voices, device permitting).
6. **ML screening estimate (trained model)** - if a report has no
   HbA1c result, a multinomial logistic-regression model trained on
   CDC NHANES 2021-2023 lab data (6,002 adults; 70% train / 30% test;
   held-out accuracy 70.5%, macro AUC 0.803) estimates the HbA1c
   class - Normal / Prediabetes / Diabetes range - from the other
   results, with probabilities shown. Guardrails: it appears only
   when at least 8 of its 18 inputs are present and the model is at
   least 45% confident, never during an emergency, and it is always
   labelled "AI estimate - NOT a test result". It never changes any
   rule-based result above. Training pipeline + evaluation report:
   the `ml/` folder of this repo.

## Tests

```bash
python3 -m unittest discover -s tests -v
# 30 tests: panic labs, overdose, severe interaction, unknown-drug
# refusal, brand matching, PII redaction, 3-language completeness,
# urine-report guard, decimal-drop checks, and a real-world report
# regression (Hoti Medical Laboratory, Mardan - Complete Blood Picture
# with differential counts, Uric Acid, and qualitative RA Factor / CRP)...
```

## Honest limits - read this before showing it to anyone

- **Handwritten prescriptions are NOT promised.** Doctor handwriting OCR
  is unreliable; the verification gate is the safety net, and typed /
  printed reports are what this MVP is actually good at.
- `data/` is a **sample educational dataset** (18 common medicines, 6
  interaction rules, 22 lab analytes). Covered labs: Hemoglobin, WBC/TLC
  (incl. dotted `T.L.C`), RBC (incl. `Red Count`), Platelets (incl.
  `Platelets Count` and Indian comma values like `3,90,000`), Glucose,
  HbA1c, Potassium, Sodium, Creatinine, Urea, ALT, Bilirubin, Calcium,
  Cholesterol, Uric Acid, the differential counts (Neutrophils,
  Lymphocytes, Monocytes, Eosinophils, Basophils), and the qualitative
  tests RA Factor and CRP (Negative = normal, Positive = abnormal, never
  an emergency on its own). A real deployment needs a
  pharmacist-verified drug database and the reporting lab's own ranges.
- The dose check ignores age, weight, kidney/liver function and other
  conditions. It is a warning layer, not a clinical decision.
- This is a patient-education aid, not a medical device. Every output
  ends with: *"This explanation is for understanding only and does not
  replace your doctor's advice."*

## Structure

```text
medisense-ai/
├── server.py            # stdlib web server + /api/analyze + /api/health
├── medisense/
│   └── engine.py        # PII, lab/med parsing, safety engine, templates
├── data/                # drugs_pakistan.csv, interactions.json, lab_ranges.json
├── web/                 # index.html, app.js, engine.js (JS mirror), data.js, style.css
├── samples/             # sample_prescription.png, sample_lab_report.png
└── tests/               # test_safety_redteam.py (unittest, stdlib only)
```

`web/data.js` is generated from `data/` - if you edit the CSV/JSON,
regenerate it so the static page stays in sync with the Python engine.
