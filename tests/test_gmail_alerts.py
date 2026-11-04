import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gmail_alerts


class GmailAlertsTest(unittest.TestCase):
    def test_sync_deduplicates_accounts_and_keeps_link_only_out_of_scoring(self):
        description = "Build and maintain production Python services. " * 12
        raw = ("From: Jobs <alerts@linkedin.com>\nSubject: Backend engineer\n"
               "Content-Type: text/plain; charset=utf-8\n\n"
               "https://www.linkedin.com/comm/jobs/view/123456?trk=email\n"
               "Job description:\n" + description).encode()
        short = ("From: Jobs <alerts@glassdoor.com>\nSubject: Engineer\n\n"
                 "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=987&src=email").encode()

        def google(url, **kwargs):
            if url == gmail_alerts.TOKEN:
                return {"access_token": "test-token"}
            if url.endswith("/messages"):
                return {"messages": [{"id": "one"}, {"id": "two"}]}
            data = raw if url.endswith("/one") else short
            return {"raw": base64.urlsafe_b64encode(data).decode().rstrip("=")}

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with gmail_alerts.database(root) as con:
                con.executemany("INSERT INTO accounts(email,refresh) VALUES(?,?)",
                                [("one@example.com", "test"), ("two@example.com", "test")])
            with patch.object(gmail_alerts, "request_json", side_effect=google), \
                 patch.object(gmail_alerts, "credentials", return_value={}):
                self.assertEqual(gmail_alerts.sync(root), {"added": 2, "errors": []})
                self.assertEqual(gmail_alerts.sync(root), {"added": 0, "errors": []})
            self.assertEqual(len(gmail_alerts.postings(root)), 1)
            self.assertEqual(gmail_alerts.postings(root)[0]["url"], "https://www.linkedin.com/jobs/view/123456/")
            accounts = gmail_alerts.status(root)["accounts"]
            self.assertTrue(all(account["synced"] and "refresh" not in account for account in accounts))
