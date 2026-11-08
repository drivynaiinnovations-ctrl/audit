from dataclasses import dataclass

class SubmissionBlocked(Exception):
    pass

@dataclass(frozen=True)
class SubmissionRequest:
    opportunity: str
    employer: str
    role: str
    requisition: str
    url: str
    approved: bool = False
    key: str | None = None

class ApplicationExecutor:
    """No ATS transport exists. All real submissions are disabled."""
    def __init__(self, guard):
        self.guard = guard

    def submit(self, request: SubmissionRequest):
        decision = self.guard.preflight(request.opportunity, request.employer,
            request.role, request.requisition, request.url, request.approved, request.key)
        if decision != 'READY_FOR_HUMAN_APPROVED_SUBMISSION':
            raise SubmissionBlocked(decision)
        raise SubmissionBlocked('PRODUCTION_TRANSPORT_DISABLED')
