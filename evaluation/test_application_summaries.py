import unittest
import uuid
from unittest.mock import Mock, patch
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from src.applications.private import application_summaries, encrypt


class ApplicationSummaryTests(unittest.TestCase):
    def test_page_uses_one_query_and_owner_bound_decryption(self):
        owner, job = uuid.uuid4(), uuid.uuid4()
        conn = Mock()
        with patch('src.applications.private.cipher', return_value=AESGCM(AESGCM.generate_key(bit_length=256))):
            ciphertext = encrypt(owner, 'application:' + str(job), {'status': 'submitted', 'next_action': 'Done', 'private': 'not returned'})
            conn.execute.return_value.fetchall.return_value = [dict(job_id=job, payload=ciphertext)]
            result = application_summaries(conn, owner, [job])
            conn.execute.assert_called_once()
            self.assertEqual(conn.execute.call_args.args[1], (owner, [job]))
            self.assertEqual(result, {str(job): {'application_status': 'submitted', 'next_action': 'Done'}})
            with self.assertRaises(InvalidTag):
                application_summaries(conn, uuid.uuid4(), [job])

    def test_empty_page_never_reads_private_table(self):
        conn = Mock()
        self.assertEqual(application_summaries(conn, uuid.uuid4(), []), {})
        conn.execute.assert_not_called()

    def test_unbounded_request_is_rejected(self):
        with self.assertRaises(ValueError):
            application_summaries(Mock(), uuid.uuid4(), [uuid.uuid4() for _ in range(26)])
