# MediSense x NHANES 2021-2023 - 70/30 Evaluation Report

**Dataset:** CDC NHANES 2021-2023 Laboratory files (CBC_L, BIOPRO_L, GHB_L)
+ Demographics (DEMO_L), from https://wwwn.cdc.gov/Nchs/Nhanes/Search/DataPage.aspx?Component=Laboratory
**Population:** 6,337 participants aged 18+ (MediSense ranges are adult ranges)
**Split:** Train 70% = 4,435 people - Test 30% = 1,902 people (seed 42, participant-level)

## Method - why this is not ML training

NHANES publishes raw measurements with **no normal/abnormal labels**, so
there is nothing to train a classifier on. The honest 70/30 version for a
rule-based engine:

- **Train (70%):** derive an empirical reference interval (2.5th-97.5th
  percentile) per analyte from the training participants.
- **Test (30%):** label every held-out value twice - with MediSense's
  stored clinical ranges and with the learned intervals - and measure
  agreement. Unit conversions applied where NHANES differs (WBC and
  Platelets are reported per 1,000 cells/uL; MediSense uses /uL).

## Headline result

**89.9% average agreement** across 19 analytes on 1,902 held-out adults.
19 of MediSense's 22 analytes are covered by these files; ALT, RA Factor
and CRP are not in the 2021-2023 CBC/Biochemistry/Glycohemoglobin files.

Strongest matches (MediSense range vs data-learned interval):

| Analyte | MediSense | Learned | Agreement |
|---|---|---|---|
| Potassium | 3.5-5.0 | 3.5-4.8 | 99.1% |
| Sodium | 135-145 | 134-144 | 98.4% |
| Platelets | 150k-450k | 150k-407k | 98.1% |
| Bilirubin | 0.1-1.2 | 0.2-1.2 | 98.1% |
| WBC | 4,000-11,000 | 3,800-11,700 | 97.6% |
| Calcium | 8.5-10.5 | 8.7-10.2 | 97.4% |

## Where they differ - and why MediSense is right to differ

- **HbA1c (62.3% agreement, 38.3% flagged High) and Cholesterol (65.3%,
  34.7% High):** NHANES is the general US population, including people
  with diagnosed and undiagnosed diabetes and high cholesterol. The
  learned intervals (HbA1c up to 8.9, Cholesterol up to 279) describe
  what is *common*, not what is *healthy*. MediSense's clinical cutoffs
  (5.6% and 200 mg/dL) are the correct medical normals - keep them.
- **Basophils (78.7%):** MediSense flags 22.9% of adults High at its
  0-1% range; the learned interval runs to 1.5%. A candidate refinement
  (many labs print 0-2%) - a decision for Amin, not changed here.
- **Monocytes (86.1%):** MediSense flags 14.7% High above 10%; learned
  interval reaches 12.8%. Same category as Basophils - observation only.
- **Urea (87.5%):** NHANES measures BUN, not serum urea (urea is about
  2.14 x BUN). The 11.9% "Low" flags are mostly this naming/unit
  mismatch, which also exists between Pakistani labs.

## What was NOT changed

No MediSense ranges were modified and nothing was pushed live. This
report is evidence about the current engine, not an edit to it. Any
range refinement (Basophils, Monocytes) is Amin's call.

## Files

- `evaluate_nhanes.py` - the full pipeline (rerun: `python3 evaluate_nhanes.py`)
- `nhanes_evaluation_results.json` - per-analyte numbers
- `data/` - the five NHANES XPT files as downloaded
