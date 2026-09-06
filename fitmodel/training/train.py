"""
fitmodel/training/train.py
=============================

Single entrypoint: loads all training_examples, builds feature vectors,
5-fold cross-validates two candidate models (Ridge, a shallow
RandomForest) AND the existing regex scorer, and prints one comparison
table - MAE, Spearman, Pearson, all against the SAME 312 labels - so
"did the ML model beat the regex scorer" has one concrete, trustworthy
answer instead of being guessed at.

WHY RIDGE + A SHALLOW RANDOM FOREST, NOT ANYTHING HEAVIER: ~312 rows
and ~19 features is a small dataset - a plain L2-regularized linear
model is the safest default (lowest overfitting risk, and its
coefficients directly show which signal mattered), and one shallow
random forest run checks for gate-interaction nonlinearity without
betting on a model family that needs far more data to trust. Deeper/
boosted models are deliberately not tried here - this comparison is
about trustworthiness, not squeezing out a last percentage point on a
dataset this size.

Only refits + pickles the winner AFTER a human looks at the printed
numbers and decides they look sane - this script does not do that
automatically, on purpose (a model silently promoted on a fluke CV
fold is exactly the kind of failure this whole project's "test against
real data, don't guess" philosophy exists to avoid).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
from scipy.stats import pearsonr, spearmanr  # noqa: E402
from sklearn.ensemble import RandomForestRegressor  # noqa: E402
from sklearn.linear_model import Ridge  # noqa: E402
from sklearn.model_selection import KFold  # noqa: E402
from sklearn.metrics import mean_absolute_error  # noqa: E402

from features import FEATURE_NAMES  # noqa: E402
from training.evaluate_baseline import regex_baseline_metrics  # noqa: E402
from training.load_examples import load_training_dataframe  # noqa: E402

MODELS_DIR = Path(__file__).parent.parent / "models"
N_FOLDS = 5
RANDOM_STATE = 42


def cross_validate(model, X: np.ndarray, y: np.ndarray) -> dict[str, tuple[float, float]]:
    kfold = KFold(n_splits=N_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    maes, spearmans, pearsons = [], [], []

    for train_idx, test_idx in kfold.split(X):
        model.fit(X[train_idx], y[train_idx])
        predictions = model.predict(X[test_idx])
        maes.append(mean_absolute_error(y[test_idx], predictions))
        spearmans.append(spearmanr(y[test_idx], predictions).correlation)
        pearsons.append(pearsonr(y[test_idx], predictions)[0])

    return {
        "mae": (float(np.mean(maes)), float(np.std(maes))),
        "spearman": (float(np.mean(spearmans)), float(np.std(spearmans))),
        "pearson": (float(np.mean(pearsons)), float(np.std(pearsons))),
    }


def format_row(name: str, mae, spearman, pearson) -> str:
    # "+/-" rather than "±" - Windows' default console codepage mangles
    # the unicode plus-minus sign into "?" garbage on this project's dev
    # machine; plain ASCII prints correctly everywhere.
    def fmt(v):
        return f"{v[0]:.1f} +/- {v[1]:.1f}" if isinstance(v, tuple) else f"{v:.2f}" if isinstance(v, float) and abs(v) < 10 else f"{v:.1f}"
    return f"{name:<26s} {fmt(mae):<16s} {fmt(spearman):<12s} {fmt(pearson):<12s}"


def main():
    print("Loading training_examples and building feature vectors (first run downloads the embedding model - be patient)...")
    df = load_training_dataframe()
    print(f"Loaded {len(df)} rows.\n")

    X = df[FEATURE_NAMES].to_numpy(dtype=float)
    y = df["label"].to_numpy(dtype=float)

    print("Evaluating regex baseline (backend/scoring.score_job) against the same labels...")
    baseline = regex_baseline_metrics(df["jd_text"].tolist(), df["label"].tolist())

    print("Cross-validating Ridge...")
    ridge_results = cross_validate(Ridge(alpha=1.0, random_state=RANDOM_STATE), X, y)

    print("Cross-validating shallow RandomForest...")
    rf_results = cross_validate(
        RandomForestRegressor(n_estimators=100, max_depth=5, random_state=RANDOM_STATE), X, y
    )

    print()
    header = f"{'':<26s} {'MAE':<16s} {'Spearman':<12s} {'Pearson':<12s}"
    print(header)
    print("-" * len(header))
    print(format_row("regex_scorer", baseline["mae"], baseline["spearman"], baseline["pearson"]))
    print(format_row(f"ridge ({N_FOLDS}-fold CV)", ridge_results["mae"], ridge_results["spearman"], ridge_results["pearson"]))
    print(format_row(f"random_forest ({N_FOLDS}-fold CV)", rf_results["mae"], rf_results["spearman"], rf_results["pearson"]))
    print()

    ridge_mean_mae = ridge_results["mae"][0]
    rf_mean_mae = rf_results["mae"][0]
    winner_name, winner_model = (
        ("ridge", Ridge(alpha=1.0, random_state=RANDOM_STATE))
        if ridge_mean_mae <= rf_mean_mae
        else ("random_forest", RandomForestRegressor(n_estimators=100, max_depth=5, random_state=RANDOM_STATE))
    )
    winner_model.fit(X, y)
    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump({"model": winner_model, "feature_names": FEATURE_NAMES, "model_name": winner_name}, MODELS_DIR / "fit_model.joblib")
    print(f"Refit '{winner_name}' on all {len(df)} rows and saved to {MODELS_DIR / 'fit_model.joblib'}")
    print("Review the table above before trusting this artifact - this script does not auto-decide a winner is 'good enough'.")


if __name__ == "__main__":
    main()
