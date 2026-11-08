from dataclasses import dataclass
from urllib.parse import urlsplit

@dataclass(frozen=True)
class AdapterResult:
    status: str
    mode: str
    destination: str
    submitted: bool = False

class HybridAdapterRouter:
    """Safe adapter boundary: only approved integration allowlists may be routed.

    This module never performs outbound HTTP requests or employer submissions.
    """
    def __init__(self, automated_hosts=()):
        self.automated_hosts = frozenset(h.lower() for h in automated_hosts)

    def prepare(self, url, duplicate=False, approval_verified=False):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname:
            return AdapterResult('BLOCK_INVALID_DESTINATION', 'BLOCKED', '')
        if duplicate:
            return AdapterResult('BLOCK_DUPLICATE', 'BLOCKED', parsed.hostname)
        mode = 'AUTOMATED_ELIGIBLE' if parsed.hostname.lower() in self.automated_hosts else 'ASSISTED'
        if not approval_verified:
            return AdapterResult('HOLD_APPROVAL', mode, parsed.hostname)
        return AdapterResult('READY_FOR_MANUAL_REVIEW', mode, parsed.hostname)

    def execute(self, *args, **kwargs):
        raise RuntimeError('LIVE_EMPLOYER_SUBMISSIONS_DISABLED')
