import io
import os
import smtplib
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.dedupe import empty_state, load_state, save_state
from src.email_notifications import (EmailError, GmailClient, deliver_email, enqueue_email,
                                     migrate_unsent_sms, render_digest, build_mime_message_with_cid,
                                     generate_test_eml)
from src.html_email import PANDA_CID, PANDA_IMAGE_PATH
from src.main import run
from src.sources.jobright import FetchResult, parse_readme
from test_jobright import HEADER, ROW


class EmailTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.state = empty_state()
        self.job = asdict(parse_readme(HEADER + ROW)[0])
        self.client = MagicMock()
        self.client.send.return_value = "<test@example.com>"

    def test_complete_digest_and_html_escaping(self):
        self.job['company'] = '<script> & Acme'
        subject, text, body = render_digest([self.job])
        self.assertIn('1 new', subject)
        for field in ('company', 'title', 'location', 'work_model', 'date_posted', 'ats', 'source_url'):
            self.assertIn(self.job[field], text)
        self.assertNotIn('<script>', body)
        self.assertIn('&lt;script&gt; &amp; Acme', body)

    def test_send_once_and_one_email_per_run(self):
        enqueue_email(self.state, [self.job], test=True)
        deliver_email(self.state, self.path, self.client)
        self.assertEqual(self.client.send.call_count, 1)
        self.assertEqual(load_state(self.path)['email']['test-v1']['status'], 'submitted')
        deliver_email(self.state, self.path, self.client)
        deliver_email(self.state, self.path, self.client)
        self.assertEqual(self.client.send.call_count, 2)

    def test_migrate_only_unsent_jobs_once(self):
        self.state['jobs'][self.job['job_id']] = self.job
        self.state['sms'] = {'job-digest': {'status': 'pending', 'job_ids': [self.job['job_id']]},
                             'test-v1': {'status': 'pending', 'job_ids': []}}
        migrate_unsent_sms(self.state)
        migrate_unsent_sms(self.state)
        self.assertEqual(len(self.state['email']), 1)
        self.assertTrue(self.state['email_migrated'])

    def test_seen_backlog_not_migrated(self):
        self.state['jobs'][self.job['job_id']] = self.job
        migrate_unsent_sms(self.state)
        self.assertEqual(self.state['email'], {})

    def test_temporary_failure_retries_at_most_three_times(self):
        enqueue_email(self.state, [], test=True)
        self.client.send.side_effect = EmailError('temporary', retryable=True)
        for _ in range(4):
            with self.assertRaises(EmailError):
                deliver_email(self.state, self.path, self.client)
        self.assertEqual(self.client.send.call_count, 3)
        self.assertEqual(load_state(self.path)['email']['test-v1']['status'], 'blocked')

    def test_uncertain_send_is_not_automatically_retried(self):
        enqueue_email(self.state, [], test=True)
        self.client.send.side_effect = EmailError('unknown', uncertain=True)
        for _ in range(2):
            with self.assertRaises(EmailError):
                deliver_email(self.state, self.path, self.client)
        self.assertEqual(self.client.send.call_count, 1)
        self.assertEqual(load_state(self.path)['email']['test-v1']['status'], 'uncertain')

    def test_interrupted_send_is_not_retried(self):
        enqueue_email(self.state, [], test=True)
        self.state['email']['test-v1']['status'] = 'sending'
        with self.assertRaises(EmailError):
            deliver_email(self.state, self.path, self.client)
        self.client.send.assert_not_called()

    @patch('src.main.fetch_readme')
    def test_queue_without_credentials_then_send_on_304(self, fetch):
        fetch.return_value = FetchResult(HEADER + ROW, 'v1')
        with redirect_stdout(io.StringIO()):
            run(self.path, queue_email=True)
        state = load_state(self.path)
        self.assertEqual(len(state['email']), 1)
        self.client.send.assert_not_called()
        fetch.return_value = FetchResult(None, 'v1')
        with redirect_stdout(io.StringIO()):
            run(self.path, email_client=self.client)
            run(self.path, email_client=self.client)
        self.client.send.assert_called_once()

    def test_corrupt_outbox_fails_closed(self):
        self.state['email'] = {'bad': {'status': 'submitted'}}
        save_state(self.path, self.state)
        with self.assertRaises(ValueError):
            load_state(self.path)


class SmtpTests(unittest.TestCase):
    def setUp(self):
        self.client = GmailClient('sender@gmail.com', 'recipient@gmail.com', 'secret')
        self.item = {'subject': 'Test', 'text': 'Plain text', 'html': '<p>HTML</p>'}

    @patch('src.email_notifications.smtplib.SMTP_SSL')
    def test_tls_auth_and_multipart_with_cid(self, factory):
        """Default send uses multipart/related with CID attachment."""
        smtp = factory.return_value
        smtp.send_message.return_value = {}
        result = self.client.send(self.item, 'test-v1')
        self.assertEqual(factory.call_args.args, ('smtp.gmail.com', 465))
        self.assertTrue(factory.call_args.kwargs['context'].check_hostname)
        self.assertEqual(factory.call_args.kwargs['timeout'], 30)
        smtp.login.assert_called_once_with('sender@gmail.com', 'secret')
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message['To'], 'recipient@gmail.com')
        self.assertEqual(message.get_content_type(), 'multipart/related')
        self.assertRegex(result, r'^<bubu-jobs-test-v1-[0-9a-f]{12}@gmail\.com>$')
        smtp.close.assert_called_once()

    @patch('src.email_notifications.smtplib.SMTP_SSL')
    def test_auth_error_is_sanitized_and_not_retried(self, factory):
        factory.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b'private info')
        with self.assertRaises(EmailError) as error:
            self.client.send(self.item, 'test-v1')
        self.assertNotIn('private info', str(error.exception))
        self.assertFalse(error.exception.retryable)
        factory.return_value.send_message.assert_not_called()

    @patch('src.email_notifications.smtplib.SMTP_SSL')
    def test_disconnect_during_send_is_uncertain(self, factory):
        factory.return_value.send_message.side_effect = smtplib.SMTPServerDisconnected('private')
        with self.assertRaises(EmailError) as error:
            self.client.send(self.item, 'test-v1')
        self.assertTrue(error.exception.uncertain)

    @patch('src.email_notifications.smtplib.SMTP_SSL', side_effect=TimeoutError())
    def test_connection_timeout_is_safe_to_retry(self, factory):
        with self.assertRaises(EmailError) as error:
            self.client.send(self.item, 'test-v1')
        self.assertTrue(error.exception.retryable)
        self.assertFalse(error.exception.uncertain)

    @patch.dict(os.environ, {'EMAIL_SENDER': 'me@gmail.com', 'EMAIL_RECIPIENT': 'me@gmail.com',
                             'EMAIL_PASSWORD': 'abcd efgh ijkl mnop'}, clear=True)
    def test_settings_and_header_injection(self):
        self.assertEqual(GmailClient.from_environment().password, 'abcdefghijklmnop')
        os.environ['EMAIL_RECIPIENT'] = 'me@gmail.com\nBcc: other@gmail.com'
        with self.assertRaises(ValueError):
            GmailClient.from_environment()


class MimeStructureTests(unittest.TestCase):
    """Tests for multipart/related MIME structure with CID inline attachment."""
    
    def test_build_mime_message_structure(self):
        """Verify the MIME structure is multipart/related with correct parts."""
        msg = build_mime_message_with_cid(
            sender="sender@example.com",
            recipient="recipient@example.com",
            subject="Test Subject",
            text_body="Plain text body",
            html_body='<html><body><img src="cid:panda-hero" /></body></html>',
            message_id="<test-123@example.com>",
        )
        
        self.assertEqual(msg.get_content_type(), "multipart/related")
        self.assertEqual(msg["From"], "sender@example.com")
        self.assertEqual(msg["To"], "recipient@example.com")
        self.assertEqual(msg["Subject"], "Test Subject")
        self.assertEqual(msg["Message-ID"], "<test-123@example.com>")
        
        payloads = msg.get_payload()
        self.assertGreaterEqual(len(payloads), 2)
        
        alt_part = payloads[0]
        self.assertEqual(alt_part.get_content_type(), "multipart/alternative")
        
        alt_payloads = alt_part.get_payload()
        self.assertEqual(len(alt_payloads), 2)
        self.assertEqual(alt_payloads[0].get_content_type(), "text/plain")
        self.assertEqual(alt_payloads[1].get_content_type(), "text/html")
        self.assertIn("Plain text body", alt_payloads[0].get_payload(decode=True).decode())
        self.assertIn("cid:panda-hero", alt_payloads[1].get_payload(decode=True).decode())
        
        if PANDA_IMAGE_PATH.exists():
            image_part = payloads[1]
            self.assertEqual(image_part.get_content_type(), "image/jpeg")
            self.assertEqual(image_part["Content-ID"], f"<{PANDA_CID}>")
            self.assertIn("inline", image_part.get("Content-Disposition", ""))
    
    def test_generate_test_eml_produces_valid_rfc822(self):
        """Verify generate_test_eml produces valid RFC822 message."""
        eml_content, html_content = generate_test_eml(
            recipient="test@example.com",
            subject="[TEST v4] New PM Jobs - Bubu Jobs",
        )
        
        self.assertIn("From: noreply@bubu-jobs.local", eml_content)
        self.assertIn("To: test@example.com", eml_content)
        self.assertIn("Subject: [TEST v4] New PM Jobs - Bubu Jobs", eml_content)
        self.assertIn("Content-Type: multipart/related", eml_content)
        self.assertIn("Content-Type: multipart/alternative", eml_content)
        self.assertIn("Content-Type: text/plain", eml_content)
        self.assertIn("Content-Type: text/html", eml_content)
        
        self.assertIn(f"cid:{PANDA_CID}", html_content)
        self.assertIn("New PM Jobs", html_content)
        
        if PANDA_IMAGE_PATH.exists():
            self.assertIn("Content-Type: image/jpeg", eml_content)
            self.assertIn(f"Content-ID: <{PANDA_CID}>", eml_content)
    
    @patch('src.email_notifications.smtplib.SMTP_SSL')
    def test_send_with_cid_creates_multipart_related(self, factory):
        """Verify GmailClient.send with use_cid=True creates multipart/related."""
        smtp = factory.return_value
        smtp.send_message.return_value = {}
        client = GmailClient('sender@gmail.com', 'recipient@gmail.com', 'secret')
        item = {
            'subject': 'Test',
            'text': 'Plain text',
            'html': '<p>HTML with hosted URL</p>',
            'html_cid': '<p>HTML with <img src="cid:panda-hero" /></p>',
        }
        
        client.send(item, 'test-cid', use_cid=True)
        
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message.get_content_type(), "multipart/related")
    
    @patch('src.email_notifications.smtplib.SMTP_SSL')
    def test_send_without_cid_creates_multipart_alternative(self, factory):
        """Verify GmailClient.send with use_cid=False creates multipart/alternative."""
        smtp = factory.return_value
        smtp.send_message.return_value = {}
        client = GmailClient('sender@gmail.com', 'recipient@gmail.com', 'secret')
        item = {
            'subject': 'Test',
            'text': 'Plain text',
            'html': '<p>HTML</p>',
        }
        
        client.send(item, 'test-no-cid', use_cid=False)
        
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message.get_content_type(), "multipart/alternative")
