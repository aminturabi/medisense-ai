"""MediSense AI - core engine. Pure Python standard library only.

Safety design (deterministic first, no LLM anywhere in this file):
  1. PII is scrubbed before anything else.
  2. Lab values are checked against normal + critical (panic) ranges.
  3. Medicines are matched against a known list. Anything not matched is
     flagged requires_pharmacist_verification and gets NO dosage text.
  4. Dose check = strength x times-per-day vs max_daily_mg from the list.
  5. Drug pairs are checked against the interaction rules.
  6. Explanations are built ONLY from the monograph fields of matched
     drugs / the lab range table - as fixed templates in EN / UR / PS.
     Because the sentences are templates, the Urdu and Pashto versions
     are human-written templates too, not machine-translated guesses.
"""
import csv, json, re
from difflib import SequenceMatcher
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

FREQ_PER_DAY = {"OD": 1, "BD": 2, "BID": 2, "TDS": 3, "TID": 3, "QID": 4, "HS": 1, "SOS": 0, "PRN": 0}
FREQ_TIMES = {
    "OD": {"en": ["morning"], "ur": ["صبح"], "ps": ["سهار"]},
    "BD": {"en": ["morning", "night"], "ur": ["صبح", "رات"], "ps": ["سهار", "شپه"]},
    "BID": {"en": ["morning", "night"], "ur": ["صبح", "رات"], "ps": ["سهار", "شپه"]},
    "TDS": {"en": ["morning", "afternoon", "night"], "ur": ["صبح", "دوپہر", "رات"], "ps": ["سهار", "غرمه", "شپه"]},
    "TID": {"en": ["morning", "afternoon", "night"], "ur": ["صبح", "دوپہر", "رات"], "ps": ["سهار", "غرمه", "شپه"]},
    "QID": {"en": ["morning", "midday", "evening", "night"], "ur": ["صبح", "دوپہر", "شام", "رات"], "ps": ["سهار", "غرمه", "ماښام", "شپه"]},
    "HS": {"en": ["night, before sleeping"], "ur": ["رات سونے سے پہلے"], "ps": ["شپه له خوب مخکې"]},
    "SOS": {"en": ["only when needed"], "ur": ["صرف ضرورت پڑنے پر"], "ps": ["یوازې کله چې اړتیا وي"]},
    "PRN": {"en": ["only when needed"], "ur": ["صرف ضرورت پڑنے پر"], "ps": ["یوازې کله چې اړتیا وي"]},
}
DISCLAIMER = {
    "en": "Note: This explanation is for understanding only and does not replace your doctor's advice.",
    "ur": "نوٹ: یہ وضاحت صرف سمجھنے کے لیے ہے اور آپ کے ڈاکٹر کے مشورے کا متبادل نہیں ہے۔",
    "ps": "یادونه: دا تشریح یوازې د پوهیدو لپاره ده او ستاسو د ډاکټر مشورې ځای نه نیسي۔",
}
EMERGENCY = {
    "en": "URGENT: One of your results is in the danger range. Go to the nearest hospital emergency now, or call Rescue 1122.",
    "ur": "فوری: آپ کا ایک نتیجہ خطرے کی حد میں ہے۔ فوراً قریبی ہسپتال کی ایمرجنسی جائیں، یا ریسکیو 1122 پر کال کریں۔",
    "ps": "بیړني: ستاسو یوه پایله د خطر په حد کې ده. سمدستي نږدې روغتون ایمرجنسي ته لاړ شئ، یا ریسکیو ۱۱۲۲ ته زنګ ووهئ۔",
}
NOT_FOUND = {
    "en": "I could not find any blood test or medicine that I know in this text. This app explains blood tests (like Hemoglobin, Glucose, Potassium) and doctor prescriptions. Urine reports and blood pressure reports are not covered yet - please ask your doctor or the lab about those.",
    "ur": "اس متن میں مجھے کوئی ایسا خون کا ٹیسٹ یا دوائی نہیں ملی جسے میں جانتا ہوں۔ یہ ایپ خون کے ٹیسٹ (جیسے ہیموگلوبن، گلوکوز، پوٹاشیم) اور ڈاکٹر کے نسخے سمجھاتی ہے۔ پیشاب کی رپورٹ اور بلڈ پریشر کی رپورٹ ابھی شامل نہیں - ان کے بارے میں اپنے ڈاکٹر یا لیب سے پوچھیں۔",
    "ps": "په دې متن کې ما ته کوم د وینې ټیسټ یا درمل ونه موندل شول چې زه یې پیژنم. دا ایپ د وینې ټیسټونه (لکه هیموګلوبین، ګلوکوز، پوټاشیم) او د ډاکټر نسخې تشریح کوي. د ادرار راپور او د وینې فشار راپور لا نه دي شامل - د هغو په اړه له خپل ډاکټر یا لابراتوار څخه وپوښتئ۔",
}
UNVERIFIED = {
    "en": "This item could not be verified automatically. Please confirm it directly with your doctor or pharmacist.",
    "ur": "اس چیز کی خودکار تصدیق نہیں ہو سکی۔ براہ کرم اس کی تصدیق براہِ راست اپنے ڈاکٹر یا فارماسسٹ سے کریں۔",
    "ps": "دا شی په اتومات ډول تصدیق نه شو. مهرباني وکړئ دا مستقیم له خپل ډاکټر یا درمل جوړونکي څخه تصدیق کړئ۔",
}


def load_data():
    labs = json.loads((DATA / "lab_ranges.json").read_text(encoding="utf-8"))["analytes"]
    interactions = json.loads((DATA / "interactions.json").read_text(encoding="utf-8"))["interactions"]
    drugs = []
    with open(DATA / "drugs_pakistan.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["brands"] = [b.strip() for b in row["brands"].split(",")]
            row["max_daily_mg"] = float(row["max_daily_mg"])
            drugs.append(row)
    return labs, drugs, interactions


LABS, DRUGS, INTERACTIONS = load_data()

# ---------- PII redaction ----------
PII_PATTERNS = [
    (re.compile(r"\b\d{5}-\d{7}-\d\b"), "[CNIC HIDDEN]"),                 # Pakistani CNIC
    (re.compile(r"\+\d{1,3}[-\s]?\d{3,5}[-\s]?\d{4,7}\b"), "[PHONE HIDDEN]"),  # international +92 / +91 ...
    (re.compile(r"\b(?:\+92|0)3\d{2}[-\s]?\d{7}\b"), "[PHONE HIDDEN]"),   # Pakistani mobile 03xx-xxxxxxx
    (re.compile(r"\b\d{10}\b"), "[PHONE HIDDEN]"),                        # bare 10-digit numbers
    (re.compile(r"\bMRN[:\s]*[A-Z0-9-]{4,}\b", re.I), "[MRN]"),
]

def redact_pii(text):
    for pat, repl in PII_PATTERNS:
        text = pat.sub(repl, text)
    return text

# ---------- Lab parsing ----------
def _num(s):
    return float(s.replace(",", ""))

# Blood-count tests that also appear, with a totally different meaning,
# in urine microscopy (e.g. "RBC 02-03 /HPF" is cells per microscope field,
# NOT a blood count). A urine report must never produce blood values.
BLOOD_COUNT_KEYS = {"hemoglobin", "wbc", "platelets", "rbc"}

def _is_urine_report(text):
    low = text.lower()
    return "urine" in low and ("hpf" in low or "microscopic" in low or "pus cell" in low)

def parse_labs(text):
    found = []
    urine_ctx = _is_urine_report(text)
    for lab in LABS:
        if urine_ctx and lab["key"] in BLOOD_COUNT_KEYS:
            continue
        for alias in lab["aliases"]:
            pat = re.compile(re.escape(alias) + r"\s*[:\-]?\s*(\d[\d,]*\.?\d*)\s*(?:" + re.escape(lab["unit"]) + r")?",
                             re.I)
            m = pat.search(text)
            if m:
                # Microscopy ranges ("RBC 02-03") and per-field units
                # ("... /HPF") are not single blood values - skip them.
                rest = text[m.end():m.end() + 10]
                if re.match(r"\s*[-\u2013]\s*\d", rest) or "hpf" in rest.lower():
                    break
                try:
                    value = _num(m.group(1))
                except ValueError:
                    break
                # Decimal-drop sanity check: a value beyond what a human body
                # can contain is almost certainly an OCR decimal error
                # (6.5 read as 65). Flag it - never fire an emergency for it.
                if lab.get("plausible_max") is not None and value > lab["plausible_max"]:
                    found.append({**lab, "value": value, "status": "suspect_decimal",
                                  "suspect_decimal": True,
                                  "normal_text": f'{lab["normal_low"]} - {lab["normal_high"]} {lab["unit"]}'})
                    break
                status = "normal"
                if lab["critical_low"] is not None and value < lab["critical_low"]:
                    status = "critical_low"
                elif lab["critical_high"] is not None and value > lab["critical_high"]:
                    status = "critical_high"
                elif value < lab["normal_low"]:
                    status = "low"
                elif value > lab["normal_high"]:
                    status = "high"
                found.append({**lab, "value": value, "status": status, "suspect_decimal": False,
                              "normal_text": f'{lab["normal_low"]} - {lab["normal_high"]} {lab["unit"]}'})
                break
    return found

# ---------- Prescription parsing ----------
def _ratio(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def match_drug(name):
    best, score = None, 0.0
    for d in DRUGS:
        for candidate in [d["generic"]] + d["brands"]:
            r = _ratio(name, candidate)
            if r > score:
                best, score = d, r
    return (best, score) if score >= 0.80 else (None, score)

MED_LINE = re.compile(
    r"(?:Tab\.?|Cap\.?|Syp\.?|Tablet|Capsule)?\s*([A-Z][A-Za-z\-+]{2,30})\s+(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml)\b"
    r"(?:[^A-Za-z0-9]{0,6}(OD|BD|BID|TDS|TID|QID|HS|SOS|PRN))?"
    r"(?:[^0-9]{0,20}?(\d+)\s*(?:days?|دن))?",
    re.I)

LAB_NAME_SET = {a.lower() for lab in LABS for a in lab["aliases"]}

def parse_meds(text):
    meds, unverified = [], []
    seen = set()
    for m in MED_LINE.finditer(text):
        raw_name, strength, unit, freq, days = m.group(1), float(m.group(2)), m.group(3).lower(), (m.group(4) or "").upper(), m.group(5)
        if raw_name.lower() in LAB_NAME_SET:
            continue  # a lab analyte line (e.g. "Hemoglobin 13.5 g/dL"), not a medicine
        if raw_name.lower() in seen:
            continue
        seen.add(raw_name.lower())
        drug, score = match_drug(raw_name)
        strength_mg = strength * (1000 if unit == "g" else 0.001 if unit == "mcg" else 1)
        if drug is None:
            unverified.append({"raw_name": raw_name, "strength": strength, "unit": unit,
                               "requires_pharmacist_verification": True})
            continue
        per_day = FREQ_PER_DAY.get(freq, 0)
        daily_mg = strength_mg * per_day if per_day else None
        meds.append({
            "name_as_written": raw_name, "generic": drug["generic"], "match_score": round(score, 2),
            "strength": strength, "unit": unit, "frequency": freq or None,
            "days": int(days) if days else None, "daily_mg": daily_mg,
            "max_daily_mg": drug["max_daily_mg"],
            "purpose_en": drug["purpose_en"], "purpose_ur": drug["purpose_ur"], "purpose_ps": drug["purpose_ps"],
            "precaution_en": drug["precaution_en"], "precaution_ur": drug["precaution_ur"], "precaution_ps": drug["precaution_ps"],
            "requires_pharmacist_verification": False,
        })
    return meds, unverified

# ---------- Safety engine (deterministic, runs before any explanation) ----------
def safety_checks(meds, labs):
    alerts = []
    for med in meds:
        if med["daily_mg"] is not None and med["daily_mg"] > med["max_daily_mg"]:
            alerts.append({"type": "max_dose", "severity": "severe", "drug": med["generic"],
                           "message_en": f'{med["generic"]}: the written dose is {med["daily_mg"]:g} mg per day, which is more than the maximum {med["max_daily_mg"]:g} mg per day in the reference list. Do NOT take it this way - confirm with your doctor or pharmacist first.',
                           "message_ur": f'{med["generic"]}: لکھی گئی خوراک روزانہ {med["daily_mg"]:g} ملی گرام ہے، جو حوالہ فہرست میں زیادہ سے زیادہ {med["max_daily_mg"]:g} ملی گرام سے زیادہ ہے۔ اس طرح نہ لیں - پہلے اپنے ڈاکٹر یا فارماسسٹ سے تصدیق کریں۔',
                           "message_ps": f'{med["generic"]}: لیکل شوی خوراک هره ورځ {med["daily_mg"]:g} ملي ګرام دی، کوم چې د مرجع په لست کې له اعظمي {med["max_daily_mg"]:g} ملي ګرام څخه ډېر دی. داسې یې مه اخلئ - لومړی له ډاکټر یا درمل جوړونکي څخه تصدیق وکړئ۔'})
    generics = {m["generic"] for m in meds}
    for rule in INTERACTIONS:
        if rule["a"] in generics and rule["b"] in generics:
            alerts.append({"type": "interaction", "severity": rule["severity"],
                           "drug": f'{rule["a"]} + {rule["b"]}',
                           "message_en": rule["message_en"], "message_ur": rule["message_ur"], "message_ps": rule["message_ps"]})
    for lab in labs:
        if lab["status"] in ("critical_low", "critical_high"):
            alerts.append({"type": "panic_lab", "severity": "emergency", "drug": lab["name"],
                           "message_en": f'{lab["name"]} is {lab["value"]:g} {lab["unit"]} - this is in the DANGER range.', **{}})
        elif lab["status"] == "suspect_decimal":
            alerts.append({"type": "decimal_check", "severity": "moderate", "drug": lab["name"],
                           "message_en": f'{lab["name"]} was read as {lab["value"]:g} {lab["unit"]} - that is more than a human body can have, so the reading probably dropped a decimal point (did it mean {lab["value"] / 10:g}?). Please check this number in the text above and fix it. No emergency alert has been raised for it.',
                           "message_ur": f'{lab["name"]} {lab["value"]:g} {lab["unit"]} پڑھا گیا ہے - یہ انسانی جسم میں ممکن حد سے زیادہ ہے، اس لیے غالباً عشاریہ (decimal point) چھوٹ گیا ہے (کیا اس کا مطلب {lab["value"] / 10:g} تھا؟)۔ براہ کرم اوپر والے متن میں یہ نمبر چیک کر کے درست کریں۔ اس کے لیے کوئی ایمرجنسی الرٹ نہیں لگایا گیا۔',
                           "message_ps": f'{lab["name"]} {lab["value"]:g} {lab["unit"]} لوستل شوی - دا د انسان په بدن کې له ممکن حد څخه ډېر دی، نو شاید عشاریه (decimal point) پاتې شوې وي (ایا مطلب یې {lab["value"] / 10:g} و؟). مهرباني وکړئ دا شمېره په پورته متن کې وګورئ او سمه یې کړئ. د دې لپاره کوم بیړنی خبرتیا نه ده ورکړل شوې۔'})
    return alerts

# ---------- Explanation builder (templates only, grounded in the tables above) ----------
def _join_times(times):
    return ", ".join(times[:-1]) + (" and " if len(times) > 1 else "") + times[-1] if times else ""

def explain(meds, labs, unverified, alerts, lang):
    lines = []
    emergency = any(a["severity"] == "emergency" for a in alerts)
    if emergency:
        lines.append(EMERGENCY[lang])
    for a in alerts:
        if a["severity"] != "emergency":
            lines.append("⚠ " + a[f"message_{lang}"])
    for med in meds:
        name = f'{med["generic"]} ({med["name_as_written"]})' if med["name_as_written"].lower() != med["generic"].lower() else med["generic"]
        lines.append(f'{name}: {med[f"purpose_{lang}"]}')
        if med["frequency"]:
            times = FREQ_TIMES[med["frequency"]][lang]
            if lang == "en":
                how = f'Take 1 tablet ({med["strength"]:g} {med["unit"]}) at these times: {_join_times(times)}'
                if med["days"]:
                    how += f' for {med["days"]} days'
                lines.append(how + ". " + med["precaution_en"])
            elif lang == "ur":
                how = f'1 گولی ({med["strength"]:g} {med["unit"]}) ان اوقات میں لیں: {"، ".join(times)}'
                if med["days"]:
                    how += f'، {med["days"]} دن تک'
                lines.append(how + "۔ " + med["precaution_ur"])
            else:
                how = f'۱ ګولۍ ({med["strength"]:g} {med["unit"]}) په دې وختونو کې واخلئ: {"، ".join(times)}'
                if med["days"]:
                    how += f'، د {med["days"]} ورځو لپاره'
                lines.append(how + "۔ " + med["precaution_ps"])
    status_word = {"normal": {"en": "Normal", "ur": "نارمل", "ps": "نورمال"},
                   "high": {"en": "High", "ur": "زیادہ", "ps": "لوړ"},
                   "low": {"en": "Low", "ur": "کم", "ps": "ټیټ"},
                   "critical_high": {"en": "DANGEROUSLY HIGH", "ur": "خطرناک حد تک زیادہ", "ps": "په خطرناکه کچه لوړ"},
                   "critical_low": {"en": "DANGEROUSLY LOW", "ur": "خطرناک حد تک کم", "ps": "په خطرناکه کچه ټیټ"},
                   "suspect_decimal": {"en": "PLEASE CHECK THE NUMBER", "ur": "براہ کرم نمبر چیک کریں", "ps": "مهرباني وکړئ شمېره وګورئ"}}
    for lab in labs:
        if lab["status"] == "suspect_decimal":
            if lang == "en":
                lines.append(f'{lab["name"]}: The value read was {lab["value"]:g} {lab["unit"]} - this looks like a reading mistake (a decimal point may be missing, for example {lab["value"] / 10:g}). Please check the printed report and fix the number in the text above.')
            elif lang == "ur":
                lines.append(f'{lab["name"]}: پڑھی گئی قیمت {lab["value"]:g} {lab["unit"]} ہے - یہ پڑھنے کی غلطی لگتی ہے (عشاریہ چھوٹ گیا ہوگا، مثلاً {lab["value"] / 10:g})۔ براہ کرم چھپی ہوئی رپورٹ دیکھ کر اوپر والے متن میں نمبر درست کریں۔')
            else:
                lines.append(f'{lab["name"]}: لوستل شوې بیه {lab["value"]:g} {lab["unit"]} ده - دا د لوستلو تېروتنه ښکاري (شاید عشاریه پاتې وي، لکه {lab["value"] / 10:g}). مهرباني وکړئ چاپ شوی راپور وګورئ او په پورته متن کې شمېره سمه کړئ۔')
            continue
        if lang == "en":
            lines.append(f'{lab["name"]}: Your result is {lab["value"]:g} {lab["unit"]}. Normal is {lab["normal_text"]}. Result: {status_word[lab["status"]]["en"]}. This test measures {lab["measures_en"]}.')
        elif lang == "ur":
            lines.append(f'{lab["name"]}: آپ کا نتیجہ {lab["value"]:g} {lab["unit"]} ہے۔ نارمل حد {lab["normal_text"]} ہے۔ نتیجہ: {status_word[lab["status"]]["ur"]}۔ یہ ٹیسٹ {lab["measures_ur"]} کو ناپتا ہے۔')
        else:
            lines.append(f'{lab["name"]}: ستاسو پایله {lab["value"]:g} {lab["unit"]} ده. نورمال حد {lab["normal_text"]} دی. پایله: {status_word[lab["status"]]["ps"]}۔ دا ټیسټ {lab["measures_ps"]} اندازه کوي۔')
    for u in unverified:
        lines.append(f'{u["raw_name"]} {u["strength"]:g} {u["unit"]}: ' + UNVERIFIED[lang])
    if not meds and not labs and not unverified and not alerts:
        # Never answer with silence: say plainly that nothing known was
        # found, and which report types ARE covered.
        lines.append(NOT_FOUND[lang])
    lines.append(DISCLAIMER[lang])
    return lines

# ---------- Main entry ----------
def analyze(raw_text):
    text = redact_pii(raw_text or "")
    labs = parse_labs(text)
    meds, unverified = parse_meds(text)
    alerts = safety_checks(meds, labs)
    result = {
        "medications": meds,
        "lab_results": [{k: lab[k] for k in ("name", "value", "unit", "status", "normal_text", "suspect_decimal")} for lab in labs],
        "unverified_items": unverified,
        "alerts": alerts,
        "emergency": any(a["severity"] == "emergency" for a in alerts),
        "requires_pharmacist_verification": bool(unverified),
        "explanations": {lang: explain(meds, labs, unverified, alerts, lang) for lang in ("en", "ur", "ps")},
        "disclaimer": DISCLAIMER,
    }
    return result
