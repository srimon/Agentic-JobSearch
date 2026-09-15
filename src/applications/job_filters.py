"""State and job-title-family filters for the jobs list.

Both are derived from stored listing text (jobs.location, jobs.title) without a schema change. The API groups the
visible, otherwise-filtered rows by (location, title), maps each distinct value here, and then filters in SQL with
``j.location = ANY(...)`` / ``j.title = ANY(...)`` so ranking, ordering and pagination stay in the database.
"""
import re
from collections import Counter

STATES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California', 'CO': 'Colorado',
    'CT': 'Connecticut', 'DE': 'Delaware', 'DC': 'District of Columbia', 'FL': 'Florida', 'GA': 'Georgia',
    'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas', 'KY': 'Kentucky',
    'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota',
    'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire',
    'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota',
    'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island',
    'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
    'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
}
REMOTE = 'remote'    # US or remote listing without an identifiable state, or a blank/unmappable location
OUTSIDE = 'outside'  # an explicit non-US country or city
SPECIAL = {REMOTE: 'Remote / no state', OUTSIDE: 'Outside the US'}
STATE_VALUES = frozenset(STATES) | frozenset(SPECIAL)

_NAMES = {name.lower(): code for code, name in STATES.items()}
_NAMES.update({'washington dc': 'DC', 'washington d c': 'DC', 'dc': 'DC', 'd c': 'DC', 'district of columbia': 'DC'})
_US = re.compile(r'(?:united states(?: of america)?|usa|us|u s a?|america)')
_WORK_MODE = re.compile(r'\b(?:remote(?:ly)?|hybrid|on[- ]?site|in[- ]office|anywhere|distributed|eligible|based|only|nationwide|flexible)\b', re.I)
# Only used when a location part names no state. Ambiguous names (Portland, Kansas City, Arlington, Columbia) are omitted.
_CITIES = {
    'new york city': 'NY', 'nyc': 'NY', 'manhattan': 'NY', 'brooklyn': 'NY', 'san francisco': 'CA', 'bay area': 'CA',
    'san francisco bay area': 'CA', 'south san francisco': 'CA', 'los angeles': 'CA', 'palo alto': 'CA',
    'mountain view': 'CA', 'san jose': 'CA', 'san diego': 'CA', 'sunnyvale': 'CA', 'menlo park': 'CA',
    'santa clara': 'CA', 'redwood city': 'CA', 'san mateo': 'CA', 'irvine': 'CA', 'oakland': 'CA', 'seattle': 'WA',
    'bellevue': 'WA', 'redmond': 'WA', 'boston': 'MA', 'cambridge ma': 'MA', 'chicago': 'IL', 'austin': 'TX',
    'dallas': 'TX', 'houston': 'TX', 'plano': 'TX', 'san antonio': 'TX', 'atlanta': 'GA', 'denver': 'CO',
    'boulder': 'CO', 'miami': 'FL', 'tampa': 'FL', 'orlando': 'FL', 'jacksonville': 'FL', 'philadelphia': 'PA',
    'pittsburgh': 'PA', 'phoenix': 'AZ', 'scottsdale': 'AZ', 'minneapolis': 'MN', 'detroit': 'MI',
    'charlotte': 'NC', 'raleigh': 'NC', 'nashville': 'TN', 'salt lake city': 'UT', 'las vegas': 'NV',
    'jersey city': 'NJ', 'hoboken': 'NJ', 'mclean': 'VA', 'baltimore': 'MD', 'bethesda': 'MD', 'st louis': 'MO',
    'indianapolis': 'IN', 'columbus oh': 'OH', 'cleveland': 'OH', 'cincinnati': 'OH', 'milwaukee': 'WI',
    'new orleans': 'LA', 'honolulu': 'HI', 'providence': 'RI', 'hartford': 'CT', 'stamford': 'CT',
    'richmond va': 'VA', 'wilmington de': 'DE',
}
_FOREIGN = {
    'canada', 'united kingdom', 'uk', 'england', 'scotland', 'wales', 'ireland', 'india', 'japan', 'china',
    'hong kong', 'taiwan', 'singapore', 'korea', 'south korea', 'australia', 'new zealand', 'germany', 'france',
    'spain', 'portugal', 'italy', 'netherlands', 'belgium', 'switzerland', 'austria', 'sweden', 'norway',
    'denmark', 'finland', 'poland', 'czech republic', 'czechia', 'romania', 'hungary', 'ukraine', 'israel',
    'united arab emirates', 'uae', 'saudi arabia', 'egypt', 'south africa', 'nigeria', 'kenya', 'mexico', 'brazil',
    'argentina', 'colombia', 'chile', 'peru', 'costa rica', 'philippines', 'vietnam', 'thailand', 'malaysia',
    'indonesia', 'emea', 'apac', 'latam', 'europe', 'asia', 'toronto', 'vancouver', 'montreal', 'ottawa',
    'calgary', 'london', 'dublin', 'berlin', 'munich', 'paris', 'amsterdam', 'madrid', 'barcelona', 'lisbon',
    'zurich', 'stockholm', 'warsaw', 'tel aviv', 'bengaluru', 'bangalore', 'hyderabad', 'pune', 'mumbai',
    'chennai', 'delhi', 'new delhi', 'gurgaon', 'gurugram', 'noida', 'tokyo', 'sydney', 'melbourne', 'manila',
    'mexico city', 'sao paulo',
}


def _key(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', text.lower())).strip()


def _state_code(segment):
    raw = re.sub(r'\b\d{5}(?:-\d{4})?\b', ' ', segment).strip()
    if re.fullmatch(r'[A-Z]{2}', raw) and raw in STATES:
        return raw
    key = _key(raw)
    if key in _NAMES and (len(key) > 2 or raw.replace('.', '').upper() == 'DC'):
        return _NAMES[key]
    return None


def _part(part):
    """Return (state codes, US marker seen, foreign marker seen) for one location of a multi-location string."""
    segments = [s for s in re.split(r',|\s+[-–—]\s+', part) if s.strip()]
    us = False; kept = []
    for segment in segments:
        cleaned = _WORK_MODE.sub(' ', segment).strip(' .-–—\t')
        key = _key(cleaned)
        if not key:
            continue
        if _US.fullmatch(key):
            us = True
            continue
        kept.append(cleaned)
    # "City, State, Country": the state is the last remaining segment that names one ("Washington, DC" is DC,
    # "Kansas City, Missouri" is MO, "Canada, Kentucky" is KY).
    for segment in reversed(kept):
        code = _state_code(segment)
        if code:
            return {code}, us, False
    keys = [_key(s) for s in kept]
    for index, key in enumerate(keys):
        city = _CITIES.get(key) or _CITIES.get(' '.join(keys[index:index + 2]))
        if city:
            return {city}, us, False
    foreign = any(key in _FOREIGN for key in keys)
    return set(), us, foreign


def location_states(location):
    """Map a listing location to state codes plus REMOTE / OUTSIDE buckets. A job matches a state if any location does."""
    text = (location or '').strip()
    if not text:
        return frozenset({REMOTE})
    codes = set(); foreign = False; us = False
    for part in re.split(r'\s*(?:;|•|\||/|\n|\bor\b)\s*', re.sub(r'[()\[\]]', ' ', text)):
        if not part.strip():
            continue
        found, part_us, part_foreign = _part(part)
        codes |= found; us = us or part_us; foreign = foreign or part_foreign
    result = set(codes)
    if foreign:
        result.add(OUTSIDE)
    if not codes and (us or not foreign):
        result.add(REMOTE)
    return frozenset(result)


# Ordered: the first matching family wins. Patterns run on a lower-cased title with punctuation removed.
TITLE_FAMILIES = [
    ('Chief Data / AI / Technology Officer', r'\bchief\b.*\bofficer\b|\b(?:cto|cio|cdo|caio)\b'),
    ('Data & AI Governance and Risk', r'\bgovernance\b|\bcompliance\b|\bcontrols?\b|\brisk\b|\blineage\b|\bprivacy\b|\baudit\b'),
    ('Security', r'\bsecurity\b|\bcyber\b|\bdata protection\b'),
    ('Product Management', r'\bproducts?\b'),
    ('Data Science & Machine Learning', r'\bdata scien|\bmachine learning\b|\bml\b|\baiml\b|\bquant\b|\bapplied ai\b'),
    ('Architecture', r'\barchitect'),
    ('AI Platforms & Infrastructure', r'\bai\b.*\b(?:platforms?|infrastructure)\b|\b(?:platforms?|infrastructure)\b.*\bai\b'),
    ('AI Engineering', r'\b(?:ai|genai|generative|agentic|artificial intelligence)\b.*\b(?:engineer|engineering|developer|development|software)\b'
                       r'|\b(?:engineer|engineering|developer|development|software)\b.*\b(?:ai|genai|generative|agentic|artificial intelligence)\b'),
    ('Data Engineering & Platforms', r'\b(?:data|analytics)\b.*\b(?:engineer|engineering|platforms?|infrastructure|pipelines?|storage|reliability)\b'
                                     r'|\b(?:engineer|engineering|platforms?|infrastructure)\b.*\bdata\b|\bdatabricks\b|\bsnowflake\b|\betl\b'),
    ('Analytics & Business Intelligence', r'\banalytics?\b|\bbusiness intelligence\b|\bbi\b|\binsights\b|\breporting\b'),
    ('Data Management & Strategy', r'\bdata\b'),
    ('AI Strategy & Transformation', r'\bai\b|\bartificial intelligence\b|\bgenai\b|\bgenerative\b|\bagentic\b'),
    ('Program & Project Management', r'\bprogram\b|\bproject\b'),
]
OTHER_TITLES = 'Other roles'
TITLE_VALUES = frozenset([label for label, _ in TITLE_FAMILIES] + [OTHER_TITLES])
_COMPILED = [(label, re.compile(pattern)) for label, pattern in TITLE_FAMILIES]


def title_family(title):
    text = _key((title or '').replace('&', ' and '))
    for label, pattern in _COMPILED:
        if pattern.search(text):
            return label
    return OTHER_TITLES


def facet_summary(rows, state='', title=''):
    """rows: [{'location','title','n'}] for the visible list before the state/title filters.

    Returns (facets, matching locations, matching titles). Each facet counts jobs under every other active filter,
    so the State counts respect the chosen job title and vice versa.
    """
    states_for = {}; family_for = {}
    state_counts = Counter(); title_counts = Counter(); locations = set(); titles = set()
    for row in rows:
        states = states_for.get(row['location'])
        if states is None:
            states = states_for[row['location']] = location_states(row['location'])
        family = family_for.get(row['title'])
        if family is None:
            family = family_for[row['title']] = title_family(row['title'])
        if state and state in states:
            locations.add(row['location'])
        if title and family == title:
            titles.add(row['title'])
        if not title or family == title:
            for code in states:
                state_counts[code] += row['n']
        if not state or state in states:
            title_counts[family] += row['n']
    order = sorted(STATES, key=lambda code: STATES[code]) + [REMOTE, OUTSIDE]
    state_facet = [{'value': code, 'label': STATES.get(code) or SPECIAL[code], 'count': state_counts.get(code, 0)}
                   for code in order if state_counts.get(code) or code == state]
    title_facet = [{'value': label, 'label': label, 'count': title_counts.get(label, 0)}
                   for label in sorted(TITLE_VALUES, key=lambda label: (-title_counts.get(label, 0), label))
                   if title_counts.get(label) or label == title]
    return {'states': state_facet, 'titles': title_facet}, sorted(locations), sorted(titles)
