import json,unittest
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
ROOT=Path(__file__).resolve().parents[1]
class SourceDirectoryTests(unittest.TestCase):
 def test_original_search_destinations_survive_consolidation(self):
  catalog=json.loads((ROOT/'frontend/app/job-board-links.json').read_text())
  boards=catalog['boards'];self.assertEqual(len(boards),len({b['name'] for b in boards}))
  for b in boards:
   url=urlsplit(b['url']);self.assertEqual(url.scheme,'https');self.assertIsNone(url.username);self.assertIsNone(url.password)
  hosts={urlsplit(b['url']).hostname.removeprefix('www.') for b in boards}
  self.assertTrue({'linkedin.com','indeed.com','glassdoor.com','ziprecruiter.com','dice.com','builtin.com','monster.com','simplyhired.com','themuse.com','himalayas.app','jooble.org','usajobs.gov','adzuna.com'}<=hosts)
  queries=' '.join(parse_qs(urlsplit(b['url']).query).get('q',[''])[0] for b in boards)
  self.assertIn('site:myworkdayjobs.com/job',queries);self.assertIn('site:jobs.lever.co',queries)
  for b in boards:
   if b['name'] in ('Glassdoor','ZipRecruiter','Built In','SimplyHired','Workday employer sites','Lever employer sites'):self.assertEqual(b['status'],'Manual search link')
 def test_employer_catalog_keeps_provider_board_identity(self):
  data=json.loads((ROOT/'config/preppilot_sources.json').read_text())['boards']
  self.assertEqual(len(data),55);self.assertEqual(len({(x['provider'],x['board']) for x in data}),55)
  self.assertEqual({x['provider'] for x in data},{'greenhouse','ashby'})
