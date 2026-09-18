"""The Discipline filter of the opportunities screen (the owner, 18 Sep 2026).

Ten disciplines in the owner's order, each with the keyword set that decides whether a listing belongs to it. A
listing matches a discipline when its title or its description holds one of that discipline's keywords, and
``/api/jobs?discipline=a,b`` keeps only the listings that match at least one of the chosen ones, so it composes
with the search, date, level, workplace, state and job-title filters already in the query.

The words live twice, once here and once in ``frontend/app/disciplines.mjs``, and ``tests/test_disciplines.py``
reads the module's JSON literal and refuses any difference, so the screen and the query can never mean different
things by the same name.

Matching is case-insensitive and word-boundary aware. ``\\y`` is PostgreSQL's word boundary, and the separator
between the words of a keyword is ``[^a-zA-Z0-9]+``, so "Data-Lineage" and "Data / Lineage" read like
"data lineage"; the last word may carry a plural "s". Every ambiguous bare noun is written as a phrase, which is
why "lineage-free tooling" is not Data lineage: the keyword is "data lineage", never "lineage" on its own.

This filters stored listing text. It changes no listing, no ranking, no eligibility and no recorded decision.
"""
import re

DISCIPLINES = [
    ('software-engineering', 'Software Engineering', [
        'software engineer', 'software engineering', 'software development', 'software developer',
        'backend engineer', 'back end engineer', 'frontend engineer', 'front end engineer',
        'full stack engineer', 'fullstack engineer', 'application developer', 'api engineer',
        'site reliability engineer', 'distributed systems engineer']),
    ('ai-engineering', 'AI Engineering', [
        'ai engineer', 'ai engineering', 'artificial intelligence engineer', 'machine learning engineer',
        'ml engineer', 'mlops', 'llm', 'large language model', 'generative ai', 'genai', 'gen ai',
        'agentic ai', 'applied ai', 'deep learning engineer', 'ai developer', 'ai platform', 'prompt engineer']),
    ('data-engineering', 'Data Engineering', [
        'data engineer', 'data engineering', 'data pipeline', 'data platform', 'etl', 'elt', 'big data',
        'data warehouse', 'data lakehouse', 'data lake', 'spark', 'databricks', 'snowflake', 'airflow',
        'dbt', 'kafka']),
    ('data-governance', 'Data Governance', [
        'data governance', 'information governance', 'governance framework', 'data steward',
        'data stewardship', 'data policy', 'data policies', 'data classification', 'data ownership',
        'metadata management', 'master data management', 'mdm', 'data catalog', 'collibra', 'alation',
        'openmetadata']),
    ('data-ingestion', 'Data Ingestion', [
        'data ingestion', 'ingestion pipeline', 'ingest data', 'data acquisition', 'data collection',
        'change data capture', 'cdc', 'batch ingestion', 'streaming ingestion', 'source connector',
        'data connector', 'fivetran', 'kafka connect']),
    ('data-loading', 'Data loading', [
        'data loading', 'data load', 'data loader', 'bulk load', 'batch load', 'bulk insert',
        'load pipeline', 'staging table', 'copy into', 'data import', 'data upload']),
    ('data-lineage', 'Data lineage', [
        'data lineage', 'column level lineage', 'lineage graph', 'lineage tracking', 'lineage metadata',
        'data provenance', 'openlineage', 'marquez', 'impact analysis']),
    ('data-quality', 'Data Quality', [
        'data quality', 'data validation', 'data profiling', 'data cleansing', 'data cleaning',
        'data accuracy', 'data integrity', 'data observability', 'data reconciliation',
        'great expectations', 'soda core', 'anomaly detection']),
    ('technical-program-management', 'Technical Program Management', [
        'technical program manager', 'technical program management', 'technical programme manager',
        'tpm', 'program manager', 'program management', 'programme management']),
    ('technical-project-management', 'Technical Project Management', [
        'technical project manager', 'technical project management', 'project manager',
        'project management', 'project delivery manager', 'pmo', 'pmp']),
]

DISCIPLINE_IDS = [identifier for identifier, _, _ in DISCIPLINES]
DISCIPLINE_VALUES = frozenset(DISCIPLINE_IDS)
LABELS = {identifier: label for identifier, label, _ in DISCIPLINES}
KEYWORDS = {identifier: keywords for identifier, _, keywords in DISCIPLINES}
# A request may not name more disciplines than exist.
MAX_CHOSEN = len(DISCIPLINE_IDS)

_SEPARATOR = '[^a-zA-Z0-9]+'


def _keyword_pattern(keyword):
    """One keyword as a PostgreSQL pattern: its words on word boundaries, any punctuation between them, plural 's'."""
    words = [word for word in re.split(r'[^a-z0-9]+', keyword.lower()) if word]
    return r'\y' + _SEPARATOR.join(words) + r's?\y'


def pattern_for(chosen):
    """The single case-insensitive pattern (``~*``) matching a listing in any of the chosen disciplines.

    Raises ValueError for an unknown id, so the route can answer 422 rather than filter on nothing.
    """
    parts = []
    for identifier in chosen:
        if identifier not in DISCIPLINE_VALUES:
            raise ValueError(identifier)
        parts.extend(_keyword_pattern(keyword) for keyword in KEYWORDS[identifier])
    if not parts:
        raise ValueError('no discipline chosen')
    return '(' + '|'.join(parts) + ')'


def parse(raw):
    """The ``discipline=`` parameter: a comma-separated list of ids, duplicates dropped, order preserved.

    Raises ValueError for an unknown id or for more ids than there are disciplines.
    """
    chosen = []
    for part in (raw or '').split(','):
        identifier = part.strip()
        if not identifier or identifier in chosen:
            continue
        if identifier not in DISCIPLINE_VALUES:
            raise ValueError(identifier)
        chosen.append(identifier)
    if len(chosen) > MAX_CHOSEN:
        raise ValueError('too many disciplines')
    return chosen


_MATCHERS = {identifier: re.compile('|'.join(
    r'\b' + _SEPARATOR.join(word for word in re.split(r'[^a-z0-9]+', keyword.lower()) if word) + r's?\b'
    for keyword in keywords), re.IGNORECASE) for identifier, _, keywords in DISCIPLINES}


def matches(identifier, text):
    """True when the text holds one of the discipline's keywords. The Python twin of the module's JavaScript
    matcher, used by the tests to state what the pattern means without a database."""
    matcher = _MATCHERS.get(identifier)
    return bool(matcher and matcher.search(text or ''))
