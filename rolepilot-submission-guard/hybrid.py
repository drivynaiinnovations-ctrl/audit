from dataclasses import dataclass
from urllib.parse import urlsplit

@dataclass(frozen=True)
class HybridPlan:
    mode: str
    next_action: str
    submission_enabled: bool = False

class HybridExecutor:
    """Plan applications safely; live employer submissions are disabled."""
    def __init__(self, guard, supported_hosts=()):
        self.guard = guard
        self.supported_hosts = frozenset(h.lower() for h in supported_hosts)

    def plan(self, request):
        # A caller-supplied approval flag is never trusted by this planner.
        decision = self.guard.preflight(request.opportunity, request.employer,
            request.role, request.requisition, request.url, False, None)
        if decision != 'HOLD_APPROVAL':
            return HybridPlan('BLOCKED', decision)
        parsed = urlsplit(request.url)
        host = (parsed.hostname or '').lower()
        mode = 'AUTOMATED_ELIGIBLE' if host in self.supported_hosts else 'ASSISTED'
        return HybridPlan(mode, 'USER_REVIEW_REQUIRED')

    def execute(self, request):
        raise RuntimeError('LIVE_EMPLOYER_SUBMISSIONS_DISABLED')
