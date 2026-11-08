import re
import sqlite3
import threading
from urllib.parse import urlsplit

BLOCK = "BLOCK_DUPLICATE"
HOLD = "HOLD_INCOMPLETE"
APPROVAL = "HOLD_APPROVAL"
READY = "READY_FOR_HUMAN_APPROVED_SUBMISSION"


def norm(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def norm_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            return ""
        return (parsed.hostname.removeprefix("www.") + parsed.path.rstrip("/")).lower()
    except ValueError:
        return ""


class Guard:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5)
        self.mutex = threading.RLock()
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS registry (
                id INTEGER PRIMARY KEY, opportunity TEXT UNIQUE, employer TEXT NOT NULL,
                role TEXT NOT NULL, requisition TEXT, url TEXT UNIQUE, status TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_employer_role ON registry(employer,role);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_employer_req ON registry(employer,requisition)
                WHERE requisition IS NOT NULL;
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, decision TEXT NOT NULL,
                reason TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
                BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
                BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
            CREATE TABLE IF NOT EXISTS requests (request_key TEXT PRIMARY KEY, decision TEXT NOT NULL);
        """)

    def _log(self, decision, reason):
        self.db.execute("INSERT INTO audit(decision,reason) VALUES (?,?)", (decision,reason))
        return decision

    def preflight(self, opportunity, employer, role, requisition, url, approved=False, key=None):
        # No outbound submission capability exists. This method only reserves a candidate.
        with self.mutex:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                if key:
                    prior = self.db.execute("SELECT decision FROM requests WHERE request_key=?", (key,)).fetchone()
                    if prior:
                        self.db.execute("COMMIT")
                        return prior[0]
                o,e,r,q,u = norm(opportunity),norm(employer),norm(role),norm(requisition),norm_url(url)
                if not all((o,e,r,q,u)):
                    decision=self._log(HOLD,"missing or invalid identity field")
                else:
                    match=self.db.execute("""SELECT 1 FROM registry WHERE opportunity=? OR url=?
                        OR (employer=? AND (role=? OR requisition=?)) LIMIT 1""",(o,u,e,r,q)).fetchone()
                    if match:
                        decision=self._log(BLOCK,"existing application or reservation")
                    elif not approved:
                        decision=self._log(APPROVAL,"explicit approval missing")
                    else:
                        self.db.execute("INSERT INTO registry(opportunity,employer,role,requisition,url,status) VALUES (?,?,?,?,?,?)",
                                        (o,e,r,q,u,"RESERVED_NOT_SUBMITTED"))
                        decision=self._log(READY,"reserved; no external submission performed")
                if key:
                    self.db.execute("INSERT INTO requests(request_key,decision) VALUES (?,?)",(key,decision))
                self.db.execute("COMMIT")
                return decision
            except (sqlite3.Error, ValueError):
                try: self.db.execute("ROLLBACK")
                except sqlite3.Error: pass
                return HOLD

    def import_existing(self, opportunity, employer, role, requisition, url):
        o,e,r,q,u=norm(opportunity),norm(employer),norm(role),norm(requisition),norm_url(url)
        if not all((o,e,r,q,u)):
            raise ValueError("incomplete existing record")
        with self.mutex:
            self.db.execute("INSERT INTO registry(opportunity,employer,role,requisition,url,status) VALUES (?,?,?,?,?,?)",
                            (o,e,r,q,u,"APPLIED"))
