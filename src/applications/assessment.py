"""Deterministic evidence assistance; never predicts an employer's ATS result."""
import re
from src.guardrails.content import findings

TOPICS={
 'Data engineering':r'data engineering', 'Data management':r'data management',
 'Data governance':r'data governance', 'Data quality':r'data quality',
 'Analytics':r'analytics', 'Business intelligence':r'business intelligence|\bBI\b',
 'AI':r'\bAI\b|artificial intelligence', 'Machine learning':r'machine learning|\bML\b',
 'Generative AI':r'generative ai|\bgenai\b|large language model|\bLLMs?\b',
 'MLOps':r'\bmlops\b', 'Data architecture':r'data architect(?:ure)?',
 'SQL':r'\bSQL\b','Python':r'\bPython\b','Spark':r'\bSpark\b',
 'Databricks':r'\bDatabricks\b','Snowflake':r'\bSnowflake\b',
 'AWS':r'\bAWS\b|amazon web services','Azure':r'\bAzure\b',
 'Google Cloud':r'\bGCP\b|google cloud','ETL/ELT':r'\b(?:ETL|ELT)\b',
 'Leadership':r'leadership|led (?:a |the )?team|managed (?:a |the )?team',
 'Strategy':r'strateg(?:y|ic)','Budget ownership':r'budget',
}

def excerpt(text,pattern):
    m=re.search(pattern,text,re.I)
    if not m:return None
    return text[max(0,m.start()-80):min(len(text),m.end()+120)].strip()

def assess(resume,job):
    description=job.get('description') or ''
    if findings(description) or findings(resume):
        return {'blocked':True,'reason':'Content requires review before assessment.'}
    topics=[]
    for name,pattern in TOPICS.items():
        evidence=excerpt(description,pattern)
        if evidence:
            resume_evidence=excerpt(resume,pattern)
            topics.append({'topic':name,'job_evidence':evidence,'resume_evidence':resume_evidence,
                           'status':'mentioned' if resume_evidence else 'not_found'})
    requirements=[]
    for sentence in re.split(r'(?<=[.!?])\s+|[\r\n]+',description):
        if re.search(r'\brequir|\bmust\b|\bminimum\b|\d+\+?\s+years|\bdegree\b|\bbachelor|\bmaster|\bPh\.?D',sentence,re.I):
            requirements.append({'text':sentence[:1000],'status':'needs_verification'})
    return {'blocked':False,'method':'Evidence check v1; mentions do not prove qualifications.',
            'topics':topics,'requirements':requirements[:25],
            'limited_source':bool(job.get('evidence',{}).get('description_is_summary')) or len(description)<500,
            'format_checks':{'readable_characters':len(resume),'email_detected':bool(re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+',resume)),
               'experience_heading':bool(re.search(r'\bexperience\b',resume,re.I)),
               'education_heading':bool(re.search(r'\beducation\b',resume,re.I))},
            'limitations':['This is not an employer ATS score or a hiring prediction.',
              'Experience duration, proficiency, degrees, eligibility and screening answers need verification.',
              'PDF/DOCX extraction can omit headers, images or layout; review the extracted text.']}
