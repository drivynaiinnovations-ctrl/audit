import unittest

from coi_connector import COIConnector, rows_from_values


OPPORTUNITIES = [[
    "Opportunity ID", "Company", "Role", "Direct Source URL", "Status", "Applied",
    "Resume URL", "Cover Letter URL", "Resume File", "Cover Letter File", "Application Fill Sheet",
], [
    "open-1", "Example", "Manager", "https://jobs.example.com/1", "READY", "FALSE",
    "https://drive.google.com/resume-old", "", "", "", "https://drive.google.com/fill",
], [
    "applied-1", "Applied Co", "Manager", "https://jobs.example.com/2", "APPLIED", "TRUE",
    "https://drive.google.com/resume", "", "", "", "",
], [
    "closed-1", "Closed Co", "Manager", "https://jobs.example.com/3", "CLOSED", "FALSE",
    "https://drive.google.com/resume", "", "", "", "",
], [
    "no-doc", "No Doc", "Manager", "https://jobs.example.com/4", "READY", "FALSE", "", "", "", "", "",
], [
    "dup-1", "Example", "Manager", "https://jobs.example.com/5", "READY", "FALSE",
    "https://drive.google.com/resume", "", "", "", "",
]]

MANIFESTS = [[
    "Manifest ID", "Opportunity ID", "Approved Resume", "Approved Cover Letter",
    "ATS Preflight Status", "Cross-Table Duplicate Gate", "Submission Gate Decision",
], [
    "manifest-1", "open-1", "https://docs.google.com/resume-approved",
    "https://docs.google.com/cover-approved", "PASS", "CLEAR", "HOLD_MANUAL_PREFLIGHT",
]]


class Reader:
    def __call__(self, sheet, unused_range):
        return OPPORTUNITIES if sheet == "Opportunities" else MANIFESTS


class COIConnectorTests(unittest.TestCase):
    def test_imports_only_eligible_unapplied_role(self):
        rows = COIConnector(Reader()).import_unapplied()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].opportunity_id, "open-1")

    def test_manifest_documents_override_opportunity_documents(self):
        row = COIConnector(Reader()).import_unapplied()[0]
        self.assertEqual(row.resume_url, "https://docs.google.com/resume-approved")
        self.assertEqual(row.cover_letter_url, "https://docs.google.com/cover-approved")
        self.assertEqual(row.manifest_id, "manifest-1")
        self.assertEqual(len(row.supporting_documents), 3)

    def test_applied_closed_missing_document_and_duplicate_are_excluded(self):
        ids = {row.opportunity_id for row in COIConnector(Reader()).import_unapplied()}
        self.assertNotIn("applied-1", ids)
        self.assertNotIn("closed-1", ids)
        self.assertNotIn("no-doc", ids)
        self.assertNotIn("dup-1", ids)

    def test_invalid_or_duplicate_headers_fail_closed(self):
        for values in ([["", "Role"]], [["Role", "Role"]]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                rows_from_values(values)

    def test_25_audit_cycles_are_deterministic_and_submission_free(self):
        expected = None
        for audit_number in range(1, 26):
            rows = COIConnector(Reader()).import_unapplied()
            snapshot = [(row.opportunity_id, row.resume_url, row.supporting_documents) for row in rows]
            if expected is None:
                expected = snapshot
            self.assertEqual(snapshot, expected, f"audit {audit_number} changed output")
            self.assertFalse(hasattr(COIConnector, "submit"), "COI connector must not submit")


if __name__ == "__main__":
    unittest.main()
