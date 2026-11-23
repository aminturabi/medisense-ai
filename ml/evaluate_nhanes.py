#!/usr/bin/env python3
"""
MediSense x NHANES 2021-2023 evaluation.

NHANES has no normal/abnormal labels, so there is nothing to train a
classifier on. Instead this does the honest 70/30 version for a
rule-based engine:

  TRAIN (70% of adults): derive an empirical reference interval
      (2.5th-97.5th percentile) for every analyte MediSense knows.
  TEST  (30% held out):  label every value twice - once with
      MediSense's stored clinical ranges, once with the intervals
      learned from the training half - and measure agreement.

Population: NHANES 2021-2023 participants aged 18+ (MediSense ranges
are adult ranges). Files: CBC_L, BIOPRO_L, GHB_L, DEMO_L (CDC NHANES).
"""
import json
import numpy as np
import pandas as pd

SEED = 42
DATA = "data"

# MediSense analyte key -> (NHANES column, multiplier to MediSense unit)
MAPPING = {
    "hemoglobin":  ("LBXHGB", 1.0),      # g/dL
    "wbc":         ("LBXWBCSI", 1000),   # 1000 cells/uL -> /uL
    "platelets":   ("LBXPLTSI", 1000),   # 1000 cells/uL -> /uL
    "rbc":         ("LBXRBCSI", 1.0),    # million/uL
    "lymphocytes": ("LBXLYPCT", 1.0),    # %
    "monocytes":   ("LBXMOPCT", 1.0),    # %
    "neutrophils": ("LBXNEPCT", 1.0),    # %
    "eosinophils": ("LBXEOPCT", 1.0),    # %
    "basophils":   ("LBXBAPCT", 1.0),    # %
    "glucose":     ("LBXSGL", 1.0),      # mg/dL (serum, non-fasting file)
    "urea":        ("LBXSBU", 1.0),      # BUN mg/dL (see report caveat)
    "creatinine":  ("LBXSCR", 1.0),      # mg/dL
    "potassium":   ("LBXSKSI", 1.0),     # mmol/L
    "sodium":      ("LBXSNASI", 1.0),    # mmol/L
    "calcium":     ("LBXSCA", 1.0),      # mg/dL
    "bilirubin":   ("LBXSTB", 1.0),      # mg/dL
    "uric_acid":   ("LBXSUA", 1.0),      # mg/dL
    "cholesterol": ("LBXSCH", 1.0),      # mg/dL
    "hba1c":       ("LBXGH", 1.0),       # %
}


def label(values, low, high):
    out = np.full(len(values), "Normal", dtype=object)
    out[values < low] = "Low"
    out[values > high] = "High"
    return out


def main():
    demo = pd.read_sas(f"{DATA}/DEMO_L.xpt", format="xport")[["SEQN", "RIDAGEYR"]]
    adults = set(demo.loc[demo["RIDAGEYR"] >= 18, "SEQN"])

    frames = {}
    for name in ["CBC_L", "BIOPRO_L", "GHB_L"]:
        frames[name] = (pd.read_sas(f"{DATA}/{name}.xpt", format="xport")
                        .drop(columns=["WTPH2YR"], errors="ignore").set_index("SEQN"))
    merged = frames["CBC_L"].join(frames["BIOPRO_L"], how="outer").join(frames["GHB_L"], how="outer")
    merged = merged.loc[merged.index.isin(adults)]
    print(f"Adults (18+) with any lab data: {len(merged)}")

    rng = np.random.default_rng(SEED)
    idx = np.array(merged.index)
    rng.shuffle(idx)
    cut = int(0.70 * len(idx))
    train_ids, test_ids = set(idx[:cut]), set(idx[cut:])
    print(f"Train 70%: {len(train_ids)} participants | Test 30%: {len(test_ids)} participants")

    ranges = {a["key"]: a for a in json.load(open("../data/lab_ranges.json"))["analytes"]}

    results = {"seed": SEED, "n_train": len(train_ids), "n_test": len(test_ids), "analytes": {}}
    for key, (col, mult) in MAPPING.items():
        if key not in ranges or ranges[key].get("type") == "qualitative":
            continue
        s = merged[col].dropna() * mult
        tr = s.loc[s.index.isin(train_ids)]
        te = s.loc[s.index.isin(test_ids)]
        if len(te) < 100:
            continue
        emp_low, emp_high = np.percentile(tr, [2.5, 97.5])
        ms_low, ms_high = ranges[key]["normal_low"], ranges[key]["normal_high"]
        lab_ms = label(te.values, ms_low, ms_high)
        lab_emp = label(te.values, emp_low, emp_high)
        agree = float((lab_ms == lab_emp).mean())
        results["analytes"][key] = {
            "name": ranges[key]["name"],
            "n_test": int(len(te)),
            "medisense_range": [ms_low, ms_high],
            "nhanes_train_interval": [round(float(emp_low), 2), round(float(emp_high), 2)],
            "test_flag_pct": {
                "Low": round(float((lab_ms == "Low").mean()) * 100, 1),
                "Normal": round(float((lab_ms == "Normal").mean()) * 100, 1),
                "High": round(float((lab_ms == "High").mean()) * 100, 1),
            },
            "agreement_pct": round(agree * 100, 1),
        }

    covered = set(results["analytes"])
    skipped = [a["key"] for a in ranges.values() if a["key"] not in covered]
    results["medisense_analytes_not_in_nhanes"] = skipped
    results["overall_agreement_pct"] = round(
        float(np.mean([v["agreement_pct"] for v in results["analytes"].values()])), 1)

    with open("nhanes_evaluation_results.json", "w") as f:
        json.dump(results, f, indent=1)
    print(f"\nCovered {len(covered)} analytes; overall agreement {results['overall_agreement_pct']}%")
    print("Not covered by these NHANES files:", skipped)


if __name__ == "__main__":
    main()
