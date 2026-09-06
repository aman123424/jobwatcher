"""
fitmodel/training/load_examples.py
=====================================

Pulls every training_examples row and builds one feature vector per
row via features.FeatureExtractor (built ONCE, reused across all 312
rows - see FeatureExtractor's own docstring for why that matters for
runtime).

TrainingExample has no `title` column (see models.py) - every row is
scored with title="" (see engineered_features.py: this means the
title-only gates - bare senior/staff/lead titles, numbered levels,
internship-in-title - never fire for training data. An accepted,
schema-driven limitation, not a bug to chase; the years/degree/
competing-stack/framework gates all still work fine from body text.
"""

import pandas as pd

from dbconn import SessionLocal, TrainingExample
from features import FeatureExtractor


def load_training_dataframe() -> pd.DataFrame:
    db = SessionLocal()
    try:
        rows = db.query(TrainingExample).all()
        jd_texts = [r.jd_text for r in rows]
        labels = [r.score for r in rows]
    finally:
        db.close()

    extractor = FeatureExtractor()
    records = [extractor.build_feature_vector(jd_text, title="") for jd_text in jd_texts]

    df = pd.DataFrame.from_records(records)
    df["label"] = labels
    df["jd_text"] = jd_texts
    return df
