from src.applications.resume_fields import linkedin_links

def test_explicit_links_only():
    assert linkedin_links('Contact: www.linkedin.com/in/example-person')==['https://www.linkedin.com/in/example-person']
    assert linkedin_links('https://linkedin.com/in/example-person/ www.linkedin.com/in/example-person')==['https://www.linkedin.com/in/example-person']
    assert linkedin_links('linkedin.com.evil.test/in/person https://evil-linkedin.com/in/person')==[]
    assert linkedin_links('https://linkedin.com@evil.test/in/person')==[]
    assert linkedin_links('No explicit link')==[]

def test_conflicts_preserved():
    assert len(linkedin_links('linkedin.com/in/one linkedin.com/in/two'))==2
