import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

INJECTION = re.compile(r'ignore.{0,35}(previous|system|developer).{0,25}(instructions|prompt)|reveal.{0,30}(system prompt|credentials)|<\|im_start\|>|<system>', re.I | re.S)
SECRET = re.compile(r'\b(?:sk-(?:proj-)?[\w-]{20,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{30,})|-----BEGIN .*PRIVATE KEY-----')


def plain_text(value):
    import html
    value=html.unescape(value or '')
    soup = BeautifulSoup(value or '', 'html.parser')
    for element in soup(['script','style','iframe','object','noscript']):
        element.decompose()
    return soup.get_text(' ', strip=True)


def findings(text):
    return [name for name, pattern in [('prompt_injection', INJECTION), ('credential', SECRET)] if pattern.search(text)]


def safe_link(url):
    try:
        p = urlsplit(url)
        return p.scheme == 'https' and bool(p.hostname) and not p.username and not p.password and p.port in (None,443)
    except ValueError:
        return False
