"""ATS transport contract with an in-memory sandbox and a production kill switch.

No employer-hosted API is contacted by this module.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class ATSReceipt:
    provider: str
    external_id: str
    status: str
    sandbox: bool

class SandboxATS:
    def __init__(self):
        self.receipts = {}
    def submit(self, application, idempotency_key):
        if not idempotency_key or not application.get('opportunity'):
            raise ValueError('INVALID_APPLICATION')
        if idempotency_key not in self.receipts:
            self.receipts[idempotency_key] = ATSReceipt('sandbox', 'test-' + str(len(self.receipts) + 1), 'SIMULATED', True)
        return self.receipts[idempotency_key]

class ProductionATS:
    def submit(self, application, idempotency_key):
        raise PermissionError('REAL_EMPLOYER_SUBMISSIONS_DISABLED')
