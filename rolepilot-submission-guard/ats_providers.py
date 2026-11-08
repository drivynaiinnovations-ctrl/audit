"""Provider-aware application transport. No live ATS submission is permitted.

Greenhouse and Lever expose public job boards, but employer-side submission APIs
may require employer authorization, custom fields and anti-bot checks.
Workday applications are tenant-specific and generally require an authenticated UI.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit

@dataclass(frozen=True)
class ProviderPlan:
    provider: str
    mode: str
    submission_enabled: bool
    reason: str

class ATSProviderRouter:
    def classify(self, url: str) -> ProviderPlan:
        try:
            p=urlsplit(url)
            if p.scheme!='https' or not p.hostname or p.username or p.password:
                return ProviderPlan('unknown','BLOCKED',False,'INVALID_URL')
            host=p.hostname.lower().rstrip('.')
            if host in ('boards.greenhouse.io','job-boards.greenhouse.io','boards.eu.greenhouse.io'):
                return ProviderPlan('greenhouse','ASSISTED',False,'EMPLOYER_AUTHORIZATION_REQUIRED')
            if host=='jobs.lever.co':
                return ProviderPlan('lever','ASSISTED',False,'EMPLOYER_AUTHORIZATION_REQUIRED')
            if host.endswith('.myworkdayjobs.com') and host!='myworkdayjobs.com':
                return ProviderPlan('workday','ASSISTED',False,'TENANT_AUTHENTICATED_WORKFLOW_REQUIRED')
            return ProviderPlan('unknown','ASSISTED',False,'UNSUPPORTED_PROVIDER')
        except ValueError:
            return ProviderPlan('unknown','BLOCKED',False,'INVALID_URL')

    def submit(self, *args, **kwargs):
        raise PermissionError('REAL_EMPLOYER_SUBMISSIONS_DISABLED')
