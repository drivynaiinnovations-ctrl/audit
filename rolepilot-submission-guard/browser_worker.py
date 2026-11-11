"""Bounded browser runner used by scheduled GitHub jobs.

Cloudflare supplies work through an injected queue client. The worker never clicks a
final submit control and stops on every authentication or anti-bot challenge.
"""

from screening import MultiPageWorkflow


class BrowserWorker:
    def __init__(self, queue, vault, browser_adapter):
        self.queue = queue
        self.workflow = MultiPageWorkflow(vault)
        self.browser = browser_adapter

    def run_once(self):
        job = self.queue.claim()
        if not job:
            return "IDLE"
        pages = self.browser.inspect_pages(job)
        result = self.workflow.prepare(pages)
        self.queue.complete(job["id"], result)
        return result["status"]

    def run(self, cycles=25):
        if cycles < 1 or cycles > 100:
            raise ValueError("cycles must be between 1 and 100")
        return [self.run_once() for _ in range(cycles)]

