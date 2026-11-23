#!/usr/bin/env python3
"""
Train MediSense's ML screening model on CDC NHANES 2021-2023.

Task: predict a person's HbA1c class from their OTHER routine lab
values (the ones MediSense already reads):

    Normal         HbA1c < 5.7
    Prediabetes    HbA1c 5.7 - 6.4
    Diabetes range HbA1c >= 6.5

Split: 70% train / 30% test, stratified, seed 42, adults 18+ only.
Two models are compared honestly; the one exported for the web app is
multinomial logistic regression because its coefficients can be
shipped as JSON and run in the browser with plain arithmetic - unless
the random forest beats it by more than 5 points of balanced accuracy.

Output: model.json (features, imputation medians, scaler, coefficients,
classes, held-out metrics) - consumed by the MediSense web app.
"""
import json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

SEED = 42
DATA = "data"

FEATURES = {  # feature name -> (NHANES column, multiplier)
    "hemoglobin":  ("LBXHGB", 1.0),
    "wbc":         ("LBXWBCSI", 1000),
    "platelets":   ("LBXPLTSI", 1000),
    "rbc":         ("LBXRBCSI", 1.0),
    "lymphocytes": ("LBXLYPCT", 1.0),
    "monocytes":   ("LBXMOPCT", 1.0),
    "neutrophils": ("LBXNEPCT", 1.0),
    "eosinophils": ("LBXEOPCT", 1.0),
    "basophils":   ("LBXBAPCT", 1.0),
    "glucose":     ("LBXSGL", 1.0),
    "urea":        ("LBXSBU", 1.0),
    "creatinine":  ("LBXSCR", 1.0),
    "potassium":   ("LBXSKSI", 1.0),
    "sodium":      ("LBXSNASI", 1.0),
    "calcium":     ("LBXSCA", 1.0),
    "bilirubin":   ("LBXSTB", 1.0),
    "uric_acid":   ("LBXSUA", 1.0),
    "cholesterol": ("LBXSCH", 1.0),
}
CLASSES = ["Normal", "Prediabetes", "Diabetes range"]


def hba1c_class(v):
    if v < 5.7:
        return 0
    if v < 6.5:
        return 1
    return 2


def main():
    demo = pd.read_sas(f"{DATA}/DEMO_L.xpt", format="xport")[["SEQN", "RIDAGEYR"]]
    adults = set(demo.loc[demo["RIDAGEYR"] >= 18, "SEQN"])

    frames = []
    for name in ["CBC_L", "BIOPRO_L", "GHB_L"]:
        f = pd.read_sas(f"{DATA}/{name}.xpt", format="xport").drop(columns=["WTPH2YR"], errors="ignore")
        frames.append(f.set_index("SEQN"))
    df = frames[0].join(frames[1], how="outer").join(frames[2], how="outer")
    df = df.loc[df.index.isin(adults)]

    X = pd.DataFrame({name: df[col] * mult for name, (col, mult) in FEATURES.items()})
    y = df["LBXGH"].map(lambda v: hba1c_class(v) if pd.notna(v) else np.nan)
    mask = y.notna()
    X, y = X[mask], y[mask].astype(int)
    print(f"Adults with an HbA1c result: {len(X)}")
    print("Class balance:", {CLASSES[i]: int((y == i).sum()) for i in range(3)})

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.30, random_state=SEED, stratify=y)
    print(f"Train 70%: {len(Xtr)} | Test 30%: {len(Xte)}")

    imputer = SimpleImputer(strategy="median")
    Xtr_i = imputer.fit_transform(Xtr)
    Xte_i = imputer.transform(Xte)
    scaler = StandardScaler()
    Xtr_s = scaler.fit_transform(Xtr_i)
    Xte_s = scaler.transform(Xte_i)

    lr = LogisticRegression(max_iter=2000)  # multinomial by default in sklearn >= 1.7
    lr.fit(Xtr_s, ytr)
    rf = RandomForestClassifier(n_estimators=300, random_state=SEED, n_jobs=-1)
    rf.fit(Xtr_i, ytr)

    def metrics(model, X_, proba_X):
        pred = model.predict(X_)
        proba = model.predict_proba(proba_X)
        return {
            "accuracy_pct": round(float(accuracy_score(yte, pred)) * 100, 1),
            "balanced_accuracy_pct": round(float(balanced_accuracy_score(yte, pred)) * 100, 1),
            "auc_macro": round(float(roc_auc_score(yte, proba, multi_class="ovr")), 3),
        }

    m_lr = metrics(lr, Xte_s, Xte_s)
    m_rf = metrics(rf, Xte_i, Xte_i)
    print("Logistic regression:", m_lr)
    print("Random forest:      ", m_rf)

    chosen = "random_forest" if m_rf["balanced_accuracy_pct"] - m_lr["balanced_accuracy_pct"] > 5 else "logistic_regression"
    print("Exporting for the web app:", chosen)
    if chosen != "logistic_regression":
        raise SystemExit("RF won by >5 pts - export format needs revisiting before shipping.")

    coef_order = np.argsort(-np.abs(lr.coef_).max(axis=0))
    top_features = [list(FEATURES)[i] for i in coef_order[:6]]

    artifact = {
        "model": "multinomial logistic regression (scikit-learn)",
        "task": "Estimate HbA1c class from other routine lab values",
        "classes": CLASSES,
        "features": list(FEATURES),
        "impute_medians": {k: float(v) for k, v in zip(FEATURES, imputer.statistics_)},
        "scaler_mean": {k: float(v) for k, v in zip(FEATURES, scaler.mean_)},
        "scaler_scale": {k: float(v) for k, v in zip(FEATURES, scaler.scale_)},
        "coef": [[float(x) for x in row] for row in lr.coef_],
        "intercept": [float(x) for x in lr.intercept_],
        "trained_on": "CDC NHANES 2021-2023, adults 18+, 70% train split, seed 42",
        "n_train": int(len(Xtr)),
        "n_test": int(len(Xte)),
        "test_metrics": m_lr,
        "random_forest_test_metrics_for_comparison": m_rf,
        "top_features": top_features,
        "warning": "Screening estimate only - not a diagnosis and not a lab result.",
    }
    with open("model.json", "w") as f:
        json.dump(artifact, f, indent=1)
    print("Wrote model.json | top features:", top_features)


if __name__ == "__main__":
    main()
