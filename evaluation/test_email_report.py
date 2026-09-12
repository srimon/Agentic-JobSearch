import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

spec=importlib.util.spec_from_file_location('email_report',Path(__file__).resolve().parents[1] / 'scripts' / 'email_report.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class EmailTests(unittest.TestCase):
 def test_report_excludes_private_fields_and_unconfirmed(self):
  text=m.render([{'company':'Example','title':'Director, Data','status':'submission_unknown','submitted':False,'demographics':'PRIVATE','receipt':'SECRET','resume':'RESUME'}])
  self.assertNotIn('PRIVATE',text);self.assertNotIn('SECRET',text);self.assertNotIn('RESUME',text)
  self.assertIn('submission_unknown',text)
 def test_tls_recipient_and_duplicate_block(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(m.smtplib,'SMTP') as factory:
   smtp=factory.return_value.__enter__.return_value;smtp.send_message.return_value={}
   journal=Path(tmp)/'mail.jsonl'
   m.deliver('report','not-a-real-credential',journal)
   smtp.starttls.assert_called_once();smtp.login.assert_called_once()
   msg=smtp.send_message.call_args.args[0]
   self.assertEqual(msg['To'],m.ADDRESS)
   self.assertEqual(journal.stat().st_mode & 0o777,0o600)
   with self.assertRaises(RuntimeError):m.deliver('report','not-a-real-credential',journal)
   self.assertEqual(smtp.send_message.call_count,1)
 def test_uncertain_send_blocks_retry(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(m.smtplib,'SMTP') as factory:
   smtp=factory.return_value.__enter__.return_value;smtp.send_message.side_effect=TimeoutError()
   journal=Path(tmp)/'mail.jsonl'
   with self.assertRaises(RuntimeError):m.deliver('report','not-a-real-credential',journal)
   self.assertIn('delivery_unknown',journal.read_text())
   with self.assertRaises(RuntimeError):m.deliver('report','not-a-real-credential',journal)
   self.assertEqual(smtp.send_message.call_count,1)
 def test_failed_auth_never_sends(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(m.smtplib,'SMTP') as factory:
   smtp=factory.return_value.__enter__.return_value;smtp.login.side_effect=m.smtplib.SMTPAuthenticationError(535,b'denied')
   journal=Path(tmp)/'mail.jsonl'
   with self.assertRaises(m.smtplib.SMTPAuthenticationError):m.deliver('report','not-a-real-credential',journal)
   smtp.send_message.assert_not_called()

if __name__=='__main__':unittest.main()
