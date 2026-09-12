"""Extract explicit profile links only. No demographic inference or network calls."""
import re

def linkedin_links(text):
    matches=re.findall(r"(?<![a-zA-Z0-9@./-])(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)(?=[/\s?#.,;:)\]}>]|$)",text,re.I)
    return sorted({'https://www.linkedin.com/in/'+slug for slug in matches})
