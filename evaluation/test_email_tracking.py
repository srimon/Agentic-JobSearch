import importlib.util
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import hashlib,json
spec=importlib.util.spec_from_file_location('sender',Path(__file__).resolve().parents[1] / 'scripts' / 'email_report.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class TrackingTests(unittest.TestCase):
 def test_status_link_and_escaping(self):
  body=m.render([{'job_id':'46ad0a49-bafc-55f3-ad51-d21cb03bec01','title':'<bad>','company':'Example','status':'needs_information'}])
  html=m.html_report(body)
  self.assertIn('Update status in Jobsearch',html)
  self.assertIn('?view=emailed&amp;job=',html)
  self.assertNotIn('<bad>',html)
 def test_tracking_only_after_success(self):
  with patch.object(m,'track_report') as track,patch.object(m,'deliver',return_value='accepted'),tempfile.TemporaryDirectory() as d:
   self.assertEqual(m.send_tracked('body',[],'dummy',Path(d)/'journal'),'accepted')
   self.assertEqual(track.call_count,2)
   self.assertTrue(track.call_args.kwargs['accepted'])
 def test_failed_send_not_tracked_as_emailed(self):
  with patch.object(m,'track_report') as track,patch.object(m,'deliver',side_effect=RuntimeError('unknown')),tempfile.TemporaryDirectory() as d:
   with self.assertRaises(RuntimeError):m.send_tracked('body',[],'dummy',Path(d)/'journal')
   self.assertEqual(track.call_count,1)
 def test_recover_history_without_resend(self):
  with patch.object(m,'track_report') as track,patch.object(m,'deliver',side_effect=RuntimeError('duplicate')),tempfile.TemporaryDirectory() as d:
   j=Path(d)/'journal';j.write_text(json.dumps({'report_hash':hashlib.sha256((m.ADDRESS+'\nbody').encode()).hexdigest(),'status':'smtp_accepted'})+'\n')
   self.assertIn('without resending',m.send_tracked('body',[],'dummy',j))
   self.assertTrue(track.call_args.kwargs['accepted'])
if __name__=='__main__':unittest.main()
