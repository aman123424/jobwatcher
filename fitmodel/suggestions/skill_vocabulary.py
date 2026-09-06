"""
fitmodel/suggestions/skill_vocabulary.py
===========================================

CONFIRMED REAL BUG, found via this module's own Phase-2 spot-check
(round 2): even after tf-idf-against-corpus and a curated boilerplate
stoplist (see corpus_stats.py), open-vocabulary n-gram extraction kept
surfacing plain generic English words as "distinctive Required-section
terms" - "requirements", "discipline", "proven", "specialized",
"position", "ability" - words that are individually rare-ish across
the 312-JD corpus (so tf-idf ranks them high) without being anything
close to a skill. No amount of stoplist patching closes this
indefinitely; the honest fix is to stop treating "statistically
distinctive" as a proxy for "is a skill" at all.

Instead, corpus_stats.top_terms() is given an EXPLICIT vocabulary to
extract from - candidates outside this list are never considered,
full stop. This is a curated general-SWE skill/tech gazetteer, built
as RESUME_SKILLS's own keyword list (Aman's actual skills - reused
directly, not re-derived) UNIONED with a modest set of common
adjacent technologies he does NOT have, specifically so real gaps
(the whole point of this module) still surface.

Known, accepted limitation: this list isn't exhaustive - a legitimately
required skill outside both RESUME_SKILLS and ADJACENT_TECH_TERMS
below (some obscure or brand-new framework) won't be caught. Expanding
this list as real postings surface real gaps is the intended workflow,
same as RESUME_SKILLS itself grew this entire session.
"""

from features._backend_path import ensure_backend_on_path

ensure_backend_on_path()

from scoring.resume_data import RESUME_SKILLS  # noqa: E402

# Common technologies/concepts NOT on Aman's resume - deliberately
# plain lowercase alphanumeric (no "#", "++", "/") since sklearn's
# default tokenizer drops tokens under 2 word-characters and doesn't
# treat punctuation as part of a token; RESUME_SKILLS keys with
# special characters (e.g. "c#/.net") are excluded from the final
# vocabulary for the same reason - handled by _normalize() below.
ADJACENT_TECH_TERMS = [
    "java", "golang", "cobol", "swift", "kotlin", "ruby", "php", "scala", "rust",
    "spring boot", "hibernate", "django", "flask", "angular", "vue", "svelte",
    "kafka", "rabbitmq", "spark", "hadoop", "airflow", "databricks", "snowflake",
    "terraform", "ansible", "jenkins", "gitlab ci", "grpc", "graphql api",
    "mongodb", "cassandra", "dynamodb", "elasticsearch", "redis", "mysql",
    "azure", "gcp", "google cloud", "microservices", "distributed systems",
    "machine learning", "deep learning", "generative ai", "large language model",
    "rag", "vector database", "oauth", "saml", "sso", "penetration testing",
    "embedded systems", "firmware", "rtos", "networking protocols", "tcp ip",
    "scrum", "devops", "site reliability", "observability", "prometheus", "grafana",
]


def _normalize(term: str) -> str:
    return term.replace("/", " ").replace("#", "").replace("++", "pp").replace(".", " ").strip()


def build_vocabulary() -> set[str]:
    return {_normalize(k) for k in RESUME_SKILLS} | {_normalize(t) for t in ADJACENT_TECH_TERMS}
