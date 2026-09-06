"""
fitmodel/training/evaluate_baseline.py
=========================================

Computes backend/scoring/score_job()'s own MAE/Spearman/Pearson
against the SAME 312 training_examples labels the ML model is
evaluated on - so train.py's comparison table is apples-to-apples,
not a number pasted in from an earlier session's informal comparison.

Scored with title="" for the SAME reason load_examples.py uses "" -
TrainingExample has no title column, so this is the fairest baseline
run possible given the schema (also means title-only gates never fire
for the regex scorer here either - a limitation shared by both sides
of the comparison, not one that favors either).
"""

import numpy as np
from scipy.stats import pearsonr, spearmanr
from sklearn.metrics import mean_absolute_error

from features._backend_path import ensure_backend_on_path

ensure_backend_on_path()

from scoring import score_job  # noqa: E402


def regex_baseline_metrics(jd_texts: list[str], labels: list[int]) -> dict[str, float]:
    predictions = [score_job({"title": "", "raw_description": text})["match_score"] for text in jd_texts]
    labels_arr = np.array(labels)
    predictions_arr = np.array(predictions)

    return {
        "mae": mean_absolute_error(labels_arr, predictions_arr),
        "spearman": spearmanr(labels_arr, predictions_arr).correlation,
        "pearson": pearsonr(labels_arr, predictions_arr)[0],
    }
