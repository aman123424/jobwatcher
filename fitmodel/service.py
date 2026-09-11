"""
fitmodel/service.py
======================

The Phase 3 HTTP wrapper the implementation plan describes - built and
locally runnable/testable, NOT deployed (see the plan: fitmodel's
dependencies won't fit a normal zip Lambda, and standing up a
container-image Lambda is a deliberately separate, later decision).

Run locally:
    venv\\Scripts\\uvicorn service:app --reload

Everything expensive (resume chunks, BM25 index, embedding model +
resume-chunk embeddings, the trained scikit-learn model if one exists)
is loaded ONCE at module import time - the same singleton reasoning
embedding_features.py's own docstring already gives; reloading any of
this per-request would turn a fast endpoint into a slow one.
"""

from pathlib import Path

import joblib
from fastapi import FastAPI
from pydantic import BaseModel

from features import FEATURE_NAMES, FeatureExtractor, load_resume_chunks
from suggestions import suggest

app = FastAPI(title="fitmodel service")

_resume_chunks = load_resume_chunks()
_extractor = FeatureExtractor(_resume_chunks)

_MODEL_PATH = Path(__file__).parent / "models" / "fit_model.joblib"
_trained = joblib.load(_MODEL_PATH) if _MODEL_PATH.exists() else None


class TailorRequest(BaseModel):
    raw_description: str
    title: str = ""


class TailorResponse(BaseModel):
    score: int | None
    model_name: str | None
    suggestions: list[dict]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_loaded": _trained is not None}


@app.post("/tailor", response_model=TailorResponse)
def tailor(request: TailorRequest) -> TailorResponse:
    score = None
    model_name = None
    if _trained is not None:
        feature_vector = _extractor.build_feature_vector(request.raw_description, request.title)
        row = [[feature_vector[name] for name in FEATURE_NAMES]]
        raw_prediction = _trained["model"].predict(row)[0]
        score = int(round(max(0.0, min(100.0, raw_prediction))))
        model_name = _trained["model_name"]

    suggestions = suggest(_resume_chunks, request.raw_description, embedding_index=_extractor.embedding_index)

    return TailorResponse(score=score, model_name=model_name, suggestions=suggestions)
