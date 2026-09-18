/**
 * The Discipline filter of the opportunities screen (the owner, 18 Sep 2026): ten disciplines, in the owner's order,
 * each with the keyword set that decides whether a listing belongs to it. A listing matches a discipline when its
 * title or its description contains one of that discipline's keywords.
 *
 * One module for the words, so the screen, the API and the tests never drift: `src/applications/disciplines.py` holds
 * the same ten with the same keywords and turns them into the PostgreSQL pattern `/api/jobs?discipline=` filters with,
 * and `tests/test_disciplines.py` reads the literal below and refuses a difference. That is why DISCIPLINES is written
 * as plain JSON: Python parses it out of this file.
 *
 * Matching is case-insensitive and word-boundary aware. The text is lower-cased and every run of characters that is
 * not a letter or a digit becomes one space first, so "Data-Lineage" and "Data / Lineage" read as "data lineage";
 * a keyword then has to fall on word boundaries, and its last word may carry a plural "s". Every keyword of a
 * discipline whose bare noun is ambiguous is a phrase, which is why "lineage-free tooling" is not Data lineage: the
 * keyword is "data lineage", never "lineage" on its own.
 *
 * This is a filter over stored listing text. It does not change a listing, its ranking, its eligibility or any
 * decision recorded against it.
 */

/* eslint-disable */
export const DISCIPLINES = [
{"id":"software-engineering","label":"Software Engineering","keywords":["software engineer","software engineering","software development","software developer","backend engineer","back end engineer","frontend engineer","front end engineer","full stack engineer","fullstack engineer","application developer","api engineer","site reliability engineer","distributed systems engineer"]},
{"id":"ai-engineering","label":"AI Engineering","keywords":["ai engineer","ai engineering","artificial intelligence engineer","machine learning engineer","ml engineer","mlops","llm","large language model","generative ai","genai","gen ai","agentic ai","applied ai","deep learning engineer","ai developer","ai platform","prompt engineer"]},
{"id":"data-engineering","label":"Data Engineering","keywords":["data engineer","data engineering","data pipeline","data platform","etl","elt","big data","data warehouse","data lakehouse","data lake","spark","databricks","snowflake","airflow","dbt","kafka"]},
{"id":"data-governance","label":"Data Governance","keywords":["data governance","information governance","governance framework","data steward","data stewardship","data policy","data policies","data classification","data ownership","metadata management","master data management","mdm","data catalog","collibra","alation","openmetadata"]},
{"id":"data-ingestion","label":"Data Ingestion","keywords":["data ingestion","ingestion pipeline","ingest data","data acquisition","data collection","change data capture","cdc","batch ingestion","streaming ingestion","source connector","data connector","fivetran","kafka connect"]},
{"id":"data-loading","label":"Data loading","keywords":["data loading","data load","data loader","bulk load","batch load","bulk insert","load pipeline","staging table","copy into","data import","data upload"]},
{"id":"data-lineage","label":"Data lineage","keywords":["data lineage","column level lineage","lineage graph","lineage tracking","lineage metadata","data provenance","openlineage","marquez","impact analysis"]},
{"id":"data-quality","label":"Data Quality","keywords":["data quality","data validation","data profiling","data cleansing","data cleaning","data accuracy","data integrity","data observability","data reconciliation","great expectations","soda core","anomaly detection"]},
{"id":"technical-program-management","label":"Technical Program Management","keywords":["technical program manager","technical program management","technical programme manager","tpm","program manager","program management","programme management"]},
{"id":"technical-project-management","label":"Technical Project Management","keywords":["technical project manager","technical project management","project manager","project management","project delivery manager","pmo","pmp"]}
];
/* eslint-enable */

/** The ids, in the owner's order: what `?discipline=` accepts and what the API validates against. */
export const DISCIPLINE_IDS = DISCIPLINES.map((item) => item.id);
const BY_ID = new Map(DISCIPLINES.map((item) => [item.id, item]));

/** The label the screen shows for an id, or the id itself when it names no discipline. */
export const disciplineLabel = (id) => (BY_ID.get(id) || {label: id}).label;

/**
 * Lower-cased, with every run of characters that is neither a letter nor a digit turned into one space, and one
 * space at each end so a keyword at the very start or end still falls on a boundary.
 */
export function normalize(text) {
  return ' ' + String(text == null ? '' : text).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim() + ' ';
}

const escape = (word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
/** One keyword as a pattern on the normalized text: its words separated by one space, a plural "s" allowed at the end. */
const keywordPattern = (keyword) => normalize(keyword).trim().split(' ').map(escape).join(' ') + 's?';

const PATTERNS = new Map(DISCIPLINES.map((item) =>
  [item.id, new RegExp('\\b(?:' + item.keywords.map(keywordPattern).join('|') + ')\\b')]));

/** True when this text holds one of the discipline's keywords. An unknown id matches nothing. */
export function matchesDiscipline(id, text) {
  const pattern = PATTERNS.get(id);
  return pattern ? pattern.test(normalize(text)) : false;
}

/** Every discipline a listing belongs to, in the owner's order, read from its title and its description. */
export function disciplinesFor(title, description) {
  const text = normalize(title) + normalize(description);
  return DISCIPLINE_IDS.filter((id) => PATTERNS.get(id).test(text));
}

/**
 * True when a listing passes the chosen disciplines: nothing chosen lets everything through, and several chosen
 * are an "or", the way the other list filters compose.
 */
export function listingMatches(chosen, title, description) {
  if (!Array.isArray(chosen) || !chosen.length) return true;
  const text = normalize(title) + normalize(description);
  return chosen.some((id) => (PATTERNS.has(id) ? PATTERNS.get(id).test(text) : false));
}
