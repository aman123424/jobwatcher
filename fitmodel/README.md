# fitmodel

A classical ML/IR resume-fit scorer, built ALONGSIDE (not replacing)
`backend/scoring`'s hand-tuned regex scorer, plus a deterministic
resume-tailoring suggestions module. No LLM calls anywhere - BM25,
local sentence embeddings, and scikit-learn only.

This is a genuinely separate component from `backend/` - its own venv,
its own requirements, no import the other direction. It reuses
`backend/scoring`'s Required/Preferred section detection, hard-filter
gates, and resume skill data directly (see each module's own docstring
for exactly what and why), rather than re-deriving equivalent logic.

## Setup

```
py -3.12 -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
```

Needs `backend/.env`'s `DATABASE_URL` to be set (same Supabase Postgres
the rest of the app uses) - `dbconn.py` reads it directly.

## Phase 1 - train and evaluate

```
venv\Scripts\python -m training.train
```

Builds features for all `training_examples` rows, cross-validates
Ridge and a shallow RandomForest against the regex scorer's own
accuracy on the SAME labels, prints a comparison table, and (if the
numbers look reasonable - a human judgment call, not automated) pickles
the winner to `models/fit_model.joblib`.

## Phase 2 - resume-tailoring suggestions

```python
from features import FeatureExtractor, load_resume_chunks
from suggestions import suggest

extractor = FeatureExtractor()
chunks = load_resume_chunks()
for s in suggest(chunks, jd_text, embedding_index=extractor.embedding_index):
    print(s["type"], "-", s["message"])
```

Run `venv\Scripts\python tests\test_suggestions.py` to sanity-check.

## Phase 3 - HTTP service (not built yet)

Deliberately deferred until Phase 1's numbers are in and a decision is
made on whether this is worth deploying at all - see the implementation
plan this was built from for the reasoning.

## Layout

- `dbconn.py` - standalone DB connection (see its own docstring for why
  it's not named `db.py`)
- `data/resume.json` - the first prose resume artifact in this repo;
  edit this when the real resume changes
- `features/` - BM25 + embedding + reused-engineered feature pipeline
- `training/` - loads examples, trains, evaluates against the regex
  baseline
- `suggestions/` - deterministic resume-tailoring suggestions
- `models/` - gitignored; trained/cached artifacts land here
