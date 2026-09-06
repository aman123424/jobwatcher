"""
fitmodel/features/pipeline.py
================================

Combines lexical (BM25), dense (embedding), and reused-engineered
features into one flat feature vector per (resume, JD) pair.

WHY THE REGEX SCORER'S OWN FINAL SCORE IS NOT A FEATURE HERE: it would
let this model just learn to re-encode backend/scoring.score_job()'s
output rather than being a genuinely independent second signal - which
would make the "does the ML model beat the regex scorer" comparison in
fitmodel/training/train.py meaningless (a model fed the answer will
always look good against it). What IS reused from backend/scoring is
EXTRACTION logic - which gate fired, how many required-vs-preferred
skills matched - facts about the JD text itself, not the regex's own
weighted verdict about them. See engineered_features.py's own
docstring for more.
"""

import json
from pathlib import Path

from . import bm25_features, embedding_features, engineered_features, jd_sections

RESUME_JSON_PATH = Path(__file__).parent.parent / "data" / "resume.json"

FEATURE_NAMES = [
    "bm25_required_max", "bm25_required_top3_mean",
    "bm25_full_max", "bm25_full_top3_mean",
    "embed_required_max_sim", "embed_required_top3_mean",
    "embed_full_max_sim", "embed_full_top3_mean",
    "required_tier_skill_count", "preferred_tier_skill_count", "unclassified_tier_skill_count",
    "gate_years", "gate_degree", "gate_title", "gate_competing_stack", "gate_internship",
    "gate_bare_senior", "gate_competing_framework", "gate_moderate_years_gap",
]


def load_resume_chunks() -> list[dict]:
    data = json.loads(RESUME_JSON_PATH.read_text(encoding="utf-8"))
    chunks = []
    for section in data["sections"]:
        for bullet in section["bullets"]:
            chunks.append({"text": bullet, "section": section["section"], "organization": section.get("organization")})
    return chunks


class FeatureExtractor:
    """
    Builds the BM25 and embedding indices over the resume ONCE (both
    are real, if small, one-time costs - BM25's tokenization and
    MiniLM's embedding pass) and reuses them across every JD scored in
    one run, rather than rebuilding a ~40-chunk index per call.
    """

    def __init__(self, resume_chunks: list[dict] | None = None):
        self.resume_chunks = resume_chunks or load_resume_chunks()
        self.bm25_index = bm25_features.ResumeBM25Index(self.resume_chunks)
        self.embedding_index = embedding_features.ResumeEmbeddingIndex(self.resume_chunks)

    def build_feature_vector(self, raw_description: str, title: str = "") -> dict[str, float]:
        haystack = jd_sections.clean_jd_text(f"{title} {raw_description}")
        required_text = jd_sections.required_section_text(haystack)

        bm25_req_max, bm25_req_top3 = self.bm25_index.max_and_top3_mean(required_text)
        bm25_full_max, bm25_full_top3 = self.bm25_index.max_and_top3_mean(haystack)
        embed_req_max, embed_req_top3 = self.embedding_index.max_and_top3_mean_sim(required_text)
        embed_full_max, embed_full_top3 = self.embedding_index.max_and_top3_mean_sim(haystack)

        features = {
            "bm25_required_max": bm25_req_max,
            "bm25_required_top3_mean": bm25_req_top3,
            "bm25_full_max": bm25_full_max,
            "bm25_full_top3_mean": bm25_full_top3,
            "embed_required_max_sim": embed_req_max,
            "embed_required_top3_mean": embed_req_top3,
            "embed_full_max_sim": embed_full_max,
            "embed_full_top3_mean": embed_full_top3,
        }
        features.update(engineered_features.skill_tier_counts(haystack))
        features.update(engineered_features.gate_flags(haystack))
        return features


def build_feature_vector(raw_description: str, title: str = "", extractor: FeatureExtractor | None = None) -> dict[str, float]:
    return (extractor or FeatureExtractor()).build_feature_vector(raw_description, title)
