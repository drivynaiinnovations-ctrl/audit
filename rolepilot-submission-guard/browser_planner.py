"""Browser application preparation boundary. Never clicks submit or uploads without consent."""
from dataclasses import dataclass
from urllib.parse import urlsplit
from ats_providers import ATSProviderRouter

@dataclass(frozen=True)
class BrowserPreparation:
    provider: str
    url: str
    status: str
    requires_human_review: bool = True
    submitted: bool = False

class BrowserApplicationPlanner:
    def __init__(self, guard, provider_router=None):
        self.guard=guard
        self.router=provider_router or ATSProviderRouter()

    def prepare(self, request):
        p=self.router.classify(request.url)
        if p.mode=='BLOCKED':
            return BrowserPreparation(p.provider,request.url,'BLOCK_INVALID_URL')
        # Approval from a caller is deliberately ignored.
        decision=self.guard.preflight(request.opportunity,request.employer,request.role,request.requisition,request.url,False,None)
        if decision=='BLOCK_DUPLICATE':
            return BrowserPreparation(p.provider,request.url,'BLOCK_DUPLICATE')
        if decision!='HOLD_APPROVAL':
            return BrowserPreparation(p.provider,request.url,'HOLD_REVIEW')
        return BrowserPreparation(p.provider,request.url,'READY_FOR_BROWSER_PREPARATION')

    def submit(self,*args,**kwargs):
        raise PermissionError('REAL_EMPLOYER_SUBMISSIONS_DISABLED')
