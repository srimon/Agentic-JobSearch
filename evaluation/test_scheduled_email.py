import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
spec=importlib.util.spec_from_file_location('sender',Path(__file__).resolve().parents[1] / 'scripts' / 'email_report.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ReportTests(unittest.TestCase):
 def test_links_escape_and_reject_unsafe(self):
  self.assertIsNone(m.application_url('javascript:alert(1)'))
  self.assertIsNone(m.application_url('https://user:password@example.com'))
  self.assertIsNone(m.application_url('https://example.com\ninjected'))
  body=m.render([{'company':'<script>','title':'Director','status':'submission_unknown','next_action':'Reconcile first','url':'https://example.com/job?a=1&b=2'}])
  html=m.html_report(body)
  self.assertIn('href="https://example.com/job?a=1&amp;b=2"',html)
  self.assertNotIn('<script>',html)
  self.assertIn('Verify the previous attempt',html)
  self.assertIn('Reconcile first',body)
 def test_scheduled_window_dedup(self):
  with tempfile.TemporaryDirectory() as d,patch.object(m,'ROOT',Path(d)):
   now=datetime(2026,9,11,15,0,tzinfo=timezone.utc)
   first=m.scheduled_body('report',now)
   self.assertEqual(first,m.scheduled_body('report',now+timedelta(hours=1)))
   self.assertNotEqual(first,m.scheduled_body('report',now+timedelta(hours=3)))
   self.assertIn('not verified',first)
if __name__=='__main__':unittest.main()
