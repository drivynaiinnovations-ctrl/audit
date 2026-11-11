// COI import -> Cloudflare Queue -> D1 job table -> scheduled browser runner.
// Nothing in this module can submit an application. Runner results claiming a
// submission are rejected and recorded as violations.

import { evaluateCOI } from "./coi.mjs";
import { readCOI, fetchDocument } from "./google.mjs";

const LEASE_SECONDS = 900;
const MAX_ATTEMPTS = 3;
export const RESULT_STATUSES = new Set([
  "READY_FOR_REVIEW_NOT_SUBMITTED",
  "HOLD_NEW_QUESTIONS", "HOLD_CAPTCHA", "HOLD_MFA", "HOLD_SIGN_IN", "HOLD_SESSION_EXPIRED",
  "HOLD_LEGAL_ATTESTATION", "HOLD_MISSING_EVIDENCE", "HOLD_FORM_CHANGED", "HOLD_PAGE_LIMIT",
  "HOLD_UNSUPPORTED_FORM", "HOLD_NAVIGATION_FAILED", "HOLD_SOURCE_UNAVAILABLE",
]);

const now = () => Math.floor(Date.now() / 1000);

async function event(env, { job_id = null, opportunity = null, event: name, detail = "", audit = false }) {
  await env.DB.prepare("INSERT INTO prep_events(job_id,opportunity,event,detail,audit) VALUES (?,?,?,?,?)")
    .bind(job_id, opportunity, name, String(detail).slice(0, 500), audit ? 1 : 0).run();
}

/** Import COI rows and enqueue eligible ones. `fixture` is only honored for audit runs. */
export async function importAndEnqueue(env, { audit = false, fixture = null, dryRun = false } = {}) {
  const source = audit ? fixture : await readCOI(env);
  if (!source?.opportunities || !source?.manifests) throw new Error("COI_SOURCE_MISSING");
  const { eligible, blocked, counts } = evaluateCOI(source.opportunities, source.manifests, { audit });
  if (dryRun) {
    const tally = {};
    for (const b of blocked) tally[b.reason] = (tally[b.reason] || 0) + 1;
    return { dry_run: true, eligible: eligible.length, blocked_summary: tally, counts, submissions_enabled: false };
  }

  const queued = [];
  for (const job of eligible) {
    const prior = await env.DB.prepare(
      "SELECT 'reservation' AS src FROM submission_reservations WHERE opportunity=? OR url=? OR (employer||'|'||role)=?" +
      "UNION ALL SELECT 'prep' FROM prep_registry WHERE opportunity=? OR identity=? OR url=? LIMIT 1",
    ).bind(job.opportunity_id, job.source_url_key, job.identity, job.opportunity_id, job.identity, job.source_url_key).first();
    if (prior) {
      blocked.push({ opportunity_id: job.opportunity_id, row: job.source_row, reason: prior.src === "prep" ? "BLOCK_ALREADY_QUEUED" : "BLOCK_EXISTING_RESERVATION" });
      continue;
    }
    const reserved = await env.DB.prepare("INSERT OR IGNORE INTO prep_registry(opportunity,identity,url,audit) VALUES (?,?,?,?)")
      .bind(job.opportunity_id, job.identity, job.source_url_key, audit ? 1 : 0).run();
    if (reserved.meta.changes !== 1) {
      blocked.push({ opportunity_id: job.opportunity_id, row: job.source_row, reason: "BLOCK_ALREADY_QUEUED" });
      continue;
    }
    try {
      await env.PREP_QUEUE.send(job, { contentType: "json" });
      queued.push(job.opportunity_id);
      await event(env, { opportunity: job.opportunity_id, event: "ENQUEUED", audit });
    } catch (err) {
      await env.DB.prepare("DELETE FROM prep_registry WHERE opportunity=?").bind(job.opportunity_id).run();
      blocked.push({ opportunity_id: job.opportunity_id, row: job.source_row, reason: "HOLD_QUEUE_UNAVAILABLE" });
    }
  }
  const summary = {};
  for (const b of blocked) summary[b.reason] = (summary[b.reason] || 0) + 1;
  await event(env, { event: "IMPORT", detail: JSON.stringify({ ...counts, queued: queued.length, blocked: summary }), audit });
  return { queued, blocked, blocked_summary: summary, counts, submissions_enabled: false };
}

/** Queue consumer: persist each message as a claimable preparation job. */
export async function consume(batch, env) {
  for (const message of batch.messages) {
    const job = message.body;
    if (job?.kind !== "prep" || typeof job.opportunity_id !== "string") { message.ack(); continue; }
    try {
      const id = crypto.randomUUID();
      const r = await env.DB.prepare("INSERT OR IGNORE INTO prep_jobs(id,opportunity,payload,audit) VALUES (?,?,?,?)")
        .bind(id, job.opportunity_id, JSON.stringify(job), job.audit ? 1 : 0).run();
      await event(env, { job_id: r.meta.changes === 1 ? id : null, opportunity: job.opportunity_id,
        event: r.meta.changes === 1 ? "JOB_READY" : "DUPLICATE_MESSAGE_IGNORED", audit: job.audit });
      message.ack();
    } catch {
      message.retry({ delaySeconds: 30 });
    }
  }
}

export async function claim(env, { audit = false } = {}) {
  const t = now();
  const row = await env.DB.prepare(
    "UPDATE prep_jobs SET status='CLAIMED', lease_until=?, attempts=attempts+1, updated_at=CURRENT_TIMESTAMP " +
    "WHERE id=(SELECT id FROM prep_jobs WHERE audit=? AND attempts<? AND (status='READY' OR (status='CLAIMED' AND lease_until<?)) " +
    "ORDER BY created_at, id LIMIT 1) RETURNING id, payload, attempts, lease_until",
  ).bind(t + LEASE_SECONDS, audit ? 1 : 0, MAX_ATTEMPTS, t).first();
  if (!row) return null;
  await event(env, { job_id: row.id, event: "CLAIMED", detail: "attempt " + row.attempts, audit });
  return { id: row.id, lease_until: row.lease_until, attempts: row.attempts, job: JSON.parse(row.payload) };
}

export function validateResult(result) {
  if (!result || typeof result !== "object") return "INVALID_RESULT";
  if (result.submitted !== false || result.final_submit_clicked !== false) return "SUBMISSION_VIOLATION";
  if (!RESULT_STATUSES.has(result.status)) return "INVALID_STATUS";
  if (!Number.isInteger(result.pages) || result.pages < 0 || result.pages > 50) return "INVALID_PAGES";
  if (result.new_questions && (!Array.isArray(result.new_questions) || result.new_questions.length > 100)) return "INVALID_QUESTIONS";
  return "";
}

export async function complete(env, body) {
  const row = await env.DB.prepare("SELECT id, opportunity, status, lease_until, audit FROM prep_jobs WHERE id=?").bind(String(body?.job_id || "")).first();
  if (!row) return { status: 404, body: { decision: "HOLD", reason: "JOB_NOT_FOUND" } };
  if (row.status !== "CLAIMED" || row.lease_until < now()) return { status: 409, body: { decision: "HOLD", reason: "LEASE_NOT_HELD" } };
  const invalid = validateResult(body.result);
  if (invalid) {
    const violation = invalid === "SUBMISSION_VIOLATION";
    if (violation) await env.DB.prepare("UPDATE prep_jobs SET status='VIOLATION', updated_at=CURRENT_TIMESTAMP WHERE id=?").bind(row.id).run();
    await event(env, { job_id: row.id, opportunity: row.opportunity, event: violation ? "SUBMISSION_VIOLATION" : "RESULT_REJECTED", detail: invalid, audit: row.audit });
    return { status: 422, body: { decision: "DENY", reason: invalid } };
  }
  const result = {
    status: body.result.status, pages: body.result.pages, submitted: false, final_submit_clicked: false,
    new_questions: (body.result.new_questions || []).map((q) => String(q).slice(0, 300)),
    detail: String(body.result.detail || "").slice(0, 300),
  };
  await env.DB.prepare("UPDATE prep_jobs SET status=?, result=?, lease_until=0, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='CLAIMED'")
    .bind(result.status, JSON.stringify(result), row.id).run();
  await event(env, { job_id: row.id, opportunity: row.opportunity, event: result.status, detail: "pages " + result.pages, audit: row.audit });
  return { status: 200, body: { decision: "RECORDED", status: result.status, submissions_enabled: false } };
}

/** Serve one approved document belonging to a currently claimed job. */
export async function documentFor(env, jobId, slot, index = 0) {
  const row = await env.DB.prepare("SELECT payload, status, lease_until FROM prep_jobs WHERE id=?").bind(jobId).first();
  if (!row || row.status !== "CLAIMED" || row.lease_until < now()) return null;
  const docs = JSON.parse(row.payload).documents || {};
  const url = slot === "supporting" ? docs.supporting?.[index] : docs[slot];
  if (!url) return null;
  return fetchDocument(env, url);
}

export async function summary(env, audit) {
  const { results } = await env.DB.prepare("SELECT status, count(*) AS n FROM prep_jobs WHERE audit=? GROUP BY status").bind(audit ? 1 : 0).all();
  const violations = await env.DB.prepare("SELECT count(*) AS n FROM prep_events WHERE event='SUBMISSION_VIOLATION' AND audit=?").bind(audit ? 1 : 0).first();
  return { jobs: Object.fromEntries(results.map((r) => [r.status, r.n])), submission_violations: violations.n, submissions_enabled: false };
}

export async function purgeAudit(env) {
  await env.DB.batch([
    env.DB.prepare("DELETE FROM prep_jobs WHERE audit=1"),
    env.DB.prepare("DELETE FROM prep_registry WHERE audit=1"),
  ]);
  return { purged: true };
}
