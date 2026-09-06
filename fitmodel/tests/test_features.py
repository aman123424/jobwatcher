import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from features import FEATURE_NAMES, FeatureExtractor, load_resume_chunks

_extractor = FeatureExtractor()


def test_resume_chunks_load():
    chunks = load_resume_chunks()
    assert len(chunks) > 10
    assert all("text" in c and "section" in c for c in chunks)


def test_strong_match_scores_higher_than_weak_match():
    strong_jd = "Required: 2+ years of C#/.NET experience, building REST APIs, writing unit tests with NUnit."
    weak_jd = "Required: 8+ years of Rust systems programming for kernel-level networking."

    strong = _extractor.build_feature_vector(strong_jd, title="Software Engineer")
    weak = _extractor.build_feature_vector(weak_jd, title="Principal Engineer")

    assert strong["bm25_required_max"] > weak["bm25_required_max"]
    assert strong["embed_required_max_sim"] > weak["embed_required_max_sim"]
    # Rust triggers competing_stack, which _apply_hard_filters() checks
    # BEFORE the years gate (see hard_filters.py) - competing_stack
    # fires here, not years, since it's the higher-priority mismatch.
    assert weak["gate_competing_stack"] == 1
    assert strong["gate_years"] == 0
    assert strong["gate_competing_stack"] == 0


def test_feature_vector_has_all_declared_names():
    fv = _extractor.build_feature_vector("Python and FastAPI required.", title="Software Engineer")
    assert set(fv.keys()) == set(FEATURE_NAMES)


if __name__ == "__main__":
    test_resume_chunks_load()
    test_strong_match_scores_higher_than_weak_match()
    test_feature_vector_has_all_declared_names()
    print("All feature tests passed.")
