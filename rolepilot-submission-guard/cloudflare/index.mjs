// Worker entry: preparation pipeline routes, Queue consumer and cron import.
// Existing guard routes (health, plan, approval, execute=403) are delegated unchanged.

import guard from "./worker.js";
import { importAndEnqueue, consume, claim, complete, documentFor, summary, purgeAudit, sweepWritebacks, writebackStatus, processWriteback } from "./prep.mjs";
import { sheetsClient } from "./google.mjs";
import { ensureColumns, readBack } from "./writeback.mjs";
import { seedSynthetic, syntheticPage, syntheticEvent, SYNTH_ID } from "./synthetic.mjs";

const json = (v, status = 200) =>
  Response.json(v, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" } });

async function authorized(req, secret) {
  if (!secret || secret.length < 32) return false;
  const hash = async (s) => new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
  const [a, b] = await Promise.all([hash(req.headers.get("authorization") || ""), hash("Bearer " + secret)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function body(req, limit = 262144) {
  if (Number(req.headers.get("content-length") || 0) > limit) throw new Error("PAYLOAD_TOO_LARGE");
  const text = await req.text();
  if (text.length > limit) throw new Error("PAYLOAD_TOO_LARGE");
  return text ? JSON.parse(text) : {};
}

const ROUTES = {
  "/api/coi/import": "OPERATOR_TOKEN",
  "/api/prep/summary": "OPERATOR_TOKEN",
  "/api/audit/purge": "OPERATOR_TOKEN",
  "/api/coi/writeback/setup": "OPERATOR_TOKEN",
  "/api/coi/writeback/status": "OPERATOR_TOKEN",
  "/api/coi/writeback/sweep": "OPERATOR_TOKEN",
  "/api/coi/synthetic/seed": "OPERATOR_TOKEN",
  "/api/runner/claim": "RUNNER_TOKEN",
  "/api/runner/complete": "RUNNER_TOKEN",
  "/api/runner/document": "RUNNER_TOKEN",
};

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const { pathname } = url;
    // Synthetic employer form for the labeled verification role only (never a real employer).
    if (pathname.startsWith("/synthetic/")) {
      const id = pathname.slice("/synthetic/apply/".length);
      if (req.method === "GET" && pathname.startsWith("/synthetic/apply/") && SYNTH_ID.test(id)) {
        return new Response(syntheticPage(id), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store",
          "x-robots-tag": "noindex", "content-security-policy": "default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'" } });
      }
      if (req.method === "POST" && (pathname === "/synthetic/step" || pathname === "/synthetic/final")) {
        let b = {};
        try { b = await body(req, 4096); } catch { /* ignore */ }
        return json({ recorded: await syntheticEvent(env, pathname.endsWith("final") ? "final" : "step", b) });
      }
      return json({ decision: "DENY", reason: "NOT_FOUND" }, 404);
    }
    const secretName = ROUTES[pathname];
    if (!secretName) return guard.fetch(req, env, ctx);
    if (req.method !== "POST") return json({ decision: "DENY", reason: "METHOD_NOT_ALLOWED" }, 405);
    if (!(await authorized(req, env[secretName]))) return json({ decision: "DENY", reason: "UNAUTHORIZED" }, 401);

    let input;
    try { input = await body(req); } catch (e) {
      return json({ decision: "HOLD", reason: e.message === "PAYLOAD_TOO_LARGE" ? e.message : "INVALID_JSON" }, 400);
    }
    const audit = input.audit === true;
    try {
      switch (pathname) {
        case "/api/coi/import": {
          if (input.fixture && !audit) return json({ decision: "DENY", reason: "FIXTURES_ONLY_IN_AUDIT_MODE" }, 403);
          const r = await importAndEnqueue(env, { audit, fixture: input.fixture, dryRun: input.dry_run === true });
          // Blocked rows are reported by opportunity ID and reason only.
          return json({ decision: "IMPORTED", ...r });
        }
        case "/api/prep/summary": return json(await summary(env, audit));
        case "/api/audit/purge": return json(await purgeAudit(env));
        case "/api/coi/writeback/setup": return json({ decision: "OK", ...(await ensureColumns(sheetsClient(env))) });
        case "/api/coi/writeback/sweep": return json({ decision: "OK", swept: await sweepWritebacks(env) });
        case "/api/coi/writeback/status": {
          const id = String(input.opportunity_id || "");
          if (!id) return json({ decision: "HOLD", reason: "OPPORTUNITY_ID_REQUIRED" }, 400);
          if (input.job_id) await processWriteback(env, String(input.job_id));
          // Opportunity IDs, statuses and row numbers only; never other tracker columns.
          const rows = (await readBack(sheetsClient(env), id)).map(({ row, status, at, result }) => ({ row, status, at, result }));
          return json({ ...(await writebackStatus(env, id)), sheet: rows });
        }
        case "/api/coi/synthetic/seed": {
          const r = await seedSynthetic(sheetsClient(env), { id: String(input.opportunity_id || ""), origin: url.origin,
            resume: String(input.resume || ""), cover: String(input.cover_letter || "") });
          return json({ decision: "SEEDED", ...r });
        }
        case "/api/runner/claim": {
          const job = await claim(env, { audit });
          return job ? json({ decision: "CLAIMED", ...job, submissions_enabled: false }) : json({ decision: "IDLE" });
        }
        case "/api/runner/complete": {
          const r = await complete(env, input);
          return json(r.body, r.status);
        }
        case "/api/runner/document": {
          const doc = await documentFor(env, String(input.job_id || ""), String(input.slot || ""), Number(input.index || 0));
          if (!doc) return json({ decision: "HOLD", reason: "DOCUMENT_NOT_AVAILABLE" }, 404);
          return new Response(doc.body, { headers: {
            "content-type": doc.contentType, "cache-control": "no-store",
            "content-disposition": `attachment; filename="${doc.filename}"`,
          } });
        }
      }
    } catch (e) {
      const reason = /^[A-Z_:,0-9 ]+$/.test(e?.message || "") ? e.message : "INTERNAL_ERROR";
      const status = /CREDENTIAL|NOT_SHARED|SHEET_ID/.test(reason) ? 503 : /^COI_/.test(reason) ? 422 : 500;
      return json({ decision: "HOLD", reason }, status);
    }
  },

  async queue(batch, env) {
    await consume(batch, env);
  },

  async scheduled(controller, env, ctx) {
    if (!env.GOOGLE_SERVICE_ACCOUNT_JSON) return; // Not yet authorized; nothing to import.
    ctx.waitUntil((async () => {
      try {
        const r = await importAndEnqueue(env, { audit: false });
        console.log("COI import:", JSON.stringify({ queued: r.queued.length, blocked: r.blocked_summary }));
      } catch (e) { console.log("COI import held:", e.message); }
      try {
        const w = await sweepWritebacks(env);
        if (w.length) console.log("write-back sweep:", JSON.stringify(w.map((x) => x.state)));
      } catch (e) { console.log("write-back sweep held:", e.message); }
    })());
  },
};
