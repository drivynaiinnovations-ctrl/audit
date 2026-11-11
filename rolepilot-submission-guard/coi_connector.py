"""Fail-closed importer for Career Opportunity Database sheet records.

The Google transport is deliberately injected. This module contains no credentials,
personal data, or submission behavior.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit


TRUTHY = {"1", "true", "yes", "y", "applied", "submitted"}
TERMINAL_MARKERS = (
    "applied", "closed", "rejected", "withdrawn", "do not submit",
    "duplicate", "role closed", "source closed",
)


def _text(value):
    return str(value or "").strip()


def _key(value):
    return " ".join(_text(value).casefold().split())


def _url(value):
    value = _text(value)
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme == "https" and parsed.netloc else ""
    except ValueError:
        return ""


def rows_from_values(values):
    """Convert a Sheets values response into header-keyed records."""
    if not values:
        return []
    headers = [_text(header) for header in values[0]]
    if not headers or any(not header for header in headers):
        raise ValueError("COI headers are missing")
    if len(set(headers)) != len(headers):
        raise ValueError("COI headers are not unique")
    return [dict(zip(headers, list(row) + [""] * (len(headers) - len(row)))) for row in values[1:]]


@dataclass(frozen=True)
class COIApplication:
    opportunity_id: str
    company: str
    role: str
    source_url: str
    status: str
    resume_url: str
    cover_letter_url: str
    supporting_documents: tuple
    source_row: int
    manifest_id: str = ""


class COIConnector:
    """Read live COI rows through a supplied Google Sheets reader."""

    def __init__(self, reader):
        self.reader = reader

    def import_unapplied(self):
        opportunities = rows_from_values(self.reader("Opportunities", "A1:AP5003"))
        manifests = rows_from_values(self.reader("Application Manifests", "A1:AP250"))
        latest_manifest = {}
        for manifest in manifests:
            opportunity_id = _text(manifest.get("Opportunity ID"))
            if opportunity_id:
                latest_manifest[opportunity_id] = manifest

        result = []
        seen = set()
        for row_number, opportunity in enumerate(opportunities, start=2):
            opportunity_id = _text(opportunity.get("Opportunity ID"))
            company = _text(opportunity.get("Company"))
            role = _text(opportunity.get("Role"))
            status = _text(opportunity.get("Status"))
            applied = _key(opportunity.get("Applied")) in TRUTHY
            identity = (_key(company), _key(role))
            source_url = _url(opportunity.get("Direct Source URL"))
            manifest = latest_manifest.get(opportunity_id, {})
            gate = " ".join((
                _key(manifest.get("Cross-Table Duplicate Gate")),
                _key(manifest.get("Submission Gate Decision")),
                _key(manifest.get("ATS Preflight Status")),
            ))

            blocked = (
                not opportunity_id or not all(identity) or not source_url or applied
                or any(marker in _key(status) for marker in TERMINAL_MARKERS)
                or any(marker in gate for marker in TERMINAL_MARKERS)
                or "block_existing_application" in gate
                or "do_not_submit" in gate
                or identity in seen
            )
            if blocked:
                continue

            resume = _url(manifest.get("Approved Resume")) or _url(opportunity.get("Resume URL")) or _url(opportunity.get("Resume File"))
            cover = _url(manifest.get("Approved Cover Letter")) or _url(opportunity.get("Cover Letter URL")) or _url(opportunity.get("Cover Letter File"))
            attachments = []
            for candidate in (resume, cover, _url(opportunity.get("Application Fill Sheet"))):
                if candidate and candidate not in attachments:
                    attachments.append(candidate)
            if not resume:
                continue

            seen.add(identity)
            result.append(COIApplication(
                opportunity_id=opportunity_id,
                company=company,
                role=role,
                source_url=source_url,
                status=status,
                resume_url=resume,
                cover_letter_url=cover,
                supporting_documents=tuple(attachments),
                source_row=row_number,
                manifest_id=_text(manifest.get("Manifest ID")),
            ))
        return result

