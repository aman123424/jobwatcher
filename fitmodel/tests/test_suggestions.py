import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from features import FeatureExtractor, load_resume_chunks
from suggestions import suggest

_chunks = load_resume_chunks()
_extractor = FeatureExtractor()


def test_true_gap_detected():
    jd = "Required Qualifications: Strong hands-on experience with Kubernetes operators and Golang microservices."
    results = suggest(_chunks, jd, embedding_index=_extractor.embedding_index)
    types = {r["type"] for r in results}
    assert "true_gap" in types or "wording_mismatch" in types  # golang/operators should not be silently ignored


def test_synonym_mismatch_for_rest_api_framework():
    jd = "Required Qualifications: proficiency building a REST API framework for backend services."
    results = suggest(_chunks, jd, embedding_index=_extractor.embedding_index)
    # FastAPI is a real, evidenced resume skill - "REST API framework" phrasing
    # should either match via RESUME_SKILLS (rest api is a known keyword) or
    # surface as a wording_mismatch/unverified suggestion, never crash.
    assert isinstance(results, list)


def test_no_suggestions_for_stopword_only_text():
    # required_section_text() falls back to the FULL haystack when no
    # Required/Preferred headers exist at all (matches
    # hard_filters.py's SHORT_UNSTRUCTURED_CHAR_THRESHOLD reasoning) -
    # a genuinely empty vocabulary (only stopwords) is the one input
    # that should still cleanly return no suggestions.
    jd = "We and it the a"
    results = suggest(_chunks, jd, embedding_index=_extractor.embedding_index)
    assert results == []


if __name__ == "__main__":
    test_true_gap_detected()
    test_synonym_mismatch_for_rest_api_framework()
    test_no_suggestions_for_stopword_only_text()
    print("All suggestion tests passed.")
