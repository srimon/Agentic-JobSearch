import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('sender',Path(__file__).resolve().parents[1] / 'scripts' / 'email_report.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SecretTests(unittest.TestCase):
 def test_roundtrip_permissions_and_rotation(self):
  with tempfile.TemporaryDirectory() as d,patch.object(m,'ROOT',Path(d)):
   self.assertIsNone(m.load_password())
   m.save_password('abcd efgh ijkl mnop')
   p=Path(d)/'.secrets/gmail_app_password'
   self.assertEqual(p.stat().st_mode & 0o777,0o600)
   self.assertEqual(m.load_password(),'abcdefghijklmnop')
   m.save_password('ponmlkjihgfedcba')
   self.assertEqual(m.load_password(),'ponmlkjihgfedcba')
 def test_reject_world_readable(self):
  with tempfile.TemporaryDirectory() as d,patch.object(m,'ROOT',Path(d)):
   m.save_password('abcdefghijklmnop')
   (Path(d)/'.secrets/gmail_app_password').chmod(0o644)
   with self.assertRaises(RuntimeError):m.load_password()
 def test_reject_symlink(self):
  with tempfile.TemporaryDirectory() as d,patch.object(m,'ROOT',Path(d)):
   directory=m.secret_directory();target=Path(d)/'target';target.write_text('abcdefghijklmnop')
   (directory/'gmail_app_password').symlink_to(target)
   with self.assertRaises(OSError):m.load_password()
 def test_invalid_rotation_preserves_existing(self):
  with tempfile.TemporaryDirectory() as d,patch.object(m,'ROOT',Path(d)):
   m.save_password('abcdefghijklmnop')
   with self.assertRaises(RuntimeError):m.save_password('invalid')
   self.assertEqual(m.load_password(),'abcdefghijklmnop')

if __name__=='__main__':unittest.main()
