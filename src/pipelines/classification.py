import re
import json
from datetime import datetime, timezone
from src.guardrails.content import findings


def title_match(title):
    t = re.sub(r'[^a-z0-9]+',' ',title.lower()).strip()
    level = 'Other'
    if re.search(r'\b(chief|cto|cio|cdo|caio)\b',t): level='C-suite'
    elif re.search(r'\b(svp|senior vice president)\b',t): level='SVP'
    elif re.search(r'\b(vp|vice president)\b',t): level='VP'
    elif re.search(r'\b(senior|sr) director\b',t): level='Senior Director'
    elif re.search(r'\bdirector\b',t): level='Director'
    executive=bool(re.search(r'\b(chief (data|digital|information|technology|data and ai|data and analytics|ai|artificial intelligence) officer|cto|cio|caio)\b',t))
    data_area=bool(re.search(r'\b(data|analytics|business intelligence|bi|information management|information governance)\b',t))
    ai_area=bool(re.search(r'\b(ai|artificial intelligence|machine learning|ml|generative ai|genai)\b',t))
    scientific_function=bool(re.search(r'\b(biologics|drug discovery|drug design|protein design|antibody|computational biology|bioinformatics|medicinal chemistry|molecular design)\b',t))
    if scientific_function and not (data_area or executive):
        return level,'exclude','Scientific discovery or therapeutic design role, outside data/AI leadership scope'
    if re.search(r'\bcdo\b',t) and not executive:
        return level,'review','CDO requires evidence of Chief Data Officer or Chief Digital Officer'
    hit=executive or (level in ('Director','Senior Director','VP','SVP') and (data_area or ai_area))
    if not hit:
        return level,'exclude','Requires data/AI-related Director/Senior Director/VP/SVP or CTO/CIO/Chief Data Officer/Chief Digital Officer/Chief AI Officer'
    if re.search(r'\b(data cent(er|re)s?|assistant|associate|deputy|interim|fractional|field|sales|marketing|account)\b|\boffice of\b',t):
        return level,'review','Data/AI leadership scope needs review'
    return level,'match','Requested leadership level and explicit data/AI function, or approved C-suite title'


def geography(location, country='', mode='Unknown'):
    if country.upper() in ('US','USA','UNITED STATES','UNITED STATES OF AMERICA'):
        return 'us_remote_eligible' if mode=='Remote' else 'us_based'
    if country: return 'outside_us'
    if re.search(r'\b(united states|usa)\b|\bu\.s\.',location,re.I) or re.search(r'\bUS\b',location):
        return 'us_remote_eligible' if mode=='Remote' else 'us_based'
    # No guesses from city names, state abbreviations or the word remote alone.
    return 'unknown'


def posting_date(value, now=None):
    if not value or not isinstance(value,str): return None
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None: return None
        dt=dt.astimezone(timezone.utc)
        return dt if dt <= (now or datetime.now(timezone.utc)) else None
    except ValueError:
        return None


def classify(job):
    level,status,reason=title_match(job['title'])
    geo=geography(job['location'],job.pop('country',''),job['work_mode'])
    flags=findings(json.dumps(job,default=str))
    if flags:
        status='review'; reason='Content quarantined: '+', '.join(flags)
        # Sensitive content is never sent to the UI or written into audit details.
        if 'credential' in flags:
            # Exclude the whole record: secrets can occur in any field, including evidence.
            return {'match_status':'exclude','reason':'Sensitive content rejected'}
    if status=='match' and geo=='unknown':
        status='review'; reason='US eligibility is not explicit in source location'
    if geo=='outside_us': status='exclude'
    return dict(job,level=level,match_status=status,reason=reason,country_status=geo)
