// Career Opportunity Database (COI) import rules. Pure functions: no credentials, no I/O.
// Application Manifests are authoritative for documents and approved screening answers.

const text = (v) => String(v ?? "").trim();
const key = (v) => text(v).toLowerCase().replace(/\s+/g, " ");
export const identityKey = (company, role) =>
  [company, role].map((v) => key(v).replace(/[^a-z0-9]/g, "")).join("|");

export function httpsUrl(value) {
  try {
    const u = new URL(text(value));
    return u.protocol === "https:" && u.hostname && !u.username && !u.password ? u.toString() : "";
  } catch {
    return "";
  }
}

export function normalizedUrl(value) {
  try {
    const u = new URL(text(value));
    return (u.hostname.replace(/^www\./, "") + u.pathname.replace(/\/+$/, "")).toLowerCase();
  } catch {
    return "";
  }
}

export const REQUIRED_OPPORTUNITY_HEADERS = [
  "Opportunity ID", "Company", "Role", "Direct Source URL", "Status", "Applied", "Application Authorization",
];
export const REQUIRED_MANIFEST_HEADERS = ["Opportunity ID", "Approved Resume", "Approved Cover Letter"];

export function rowsFromValues(values, required = []) {
  if (!Array.isArray(values) || values.length === 0) throw new Error("COI_TAB_EMPTY");
  const headers = values[0].map(text);
  if (headers.some((h, i) => !h && headers.slice(i).some(Boolean))) throw new Error("COI_HEADER_GAP");
  const named = headers.filter(Boolean);
  if (new Set(named).size !== named.length) throw new Error("COI_HEADERS_NOT_UNIQUE");
  const missing = required.filter((h) => !named.includes(h));
  if (missing.length) throw new Error("COI_SCHEMA_MISSING:" + missing.join(","));
  return values.slice(1).map((row, i) => {
    const record = { __row: i + 2 };
    headers.forEach((h, j) => { if (h) record[h] = row?.[j] ?? ""; });
    return record;
  });
}

const APPLIED_VALUES = new Set(["1", "true", "yes", "y", "applied", "submitted", "x", "✓", "✔"]);
const AUTHORIZED_VALUES = new Set([
  "authorized", "approved", "yes", "true", "authorized to apply", "approved to apply", "apply", "go",
]);
const OPTIONAL_VALUES = new Set(["no", "false", "optional", "n/a", "na", "not required", "none"]);

// Status markers, checked in order. Each maps to a distinct block reason.
const STATUS_RULES = [
  [/\b(applied|submitted|application sent)\b/, "BLOCK_APPLIED"],
  [/\breject(ed|ion)?\b|\bdeclined\b|\bnot selected\b/, "BLOCK_REJECTED"],
  [/\bwithdr(awn|ew|aw)\b/, "BLOCK_WITHDRAWN"],
  [/\bclosed\b|\bexpired\b|\bfilled\b|\bno longer (available|accepting)\b|\barchived\b|\binactive\b/, "BLOCK_CLOSED"],
  [/\bduplicate\b|\bdupe\b/, "BLOCK_DUPLICATE"],
  [/\bdo not (submit|apply)\b|\bdo_not_submit\b|\bunauthori[sz]ed\b|\bnot authori[sz]ed\b/, "BLOCK_UNAUTHORIZED"],
];

function statusBlock(value) {
  const v = key(value).replace(/\b(not( yet)?|un) ?applied\b|\bnot submitted\b/g, " ");
  for (const [pattern, reason] of STATUS_RULES) if (pattern.test(v)) return reason;
  return "";
}

function urlList(value) {
  const parts = text(value).split(/[\s,;]+/).filter(Boolean);
  const urls = parts.map(httpsUrl);
  return { urls: urls.filter(Boolean), invalid: urls.some((u) => !u) };
}

export function parseScreeningAnswers(value) {
  const raw = text(value);
  if (!raw) return { answers: {}, unreadable: false };
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const answers = {};
      for (const [q, a] of Object.entries(parsed)) if (text(q) && text(a)) answers[text(q)] = text(a);
      return { answers, unreadable: false };
    }
  } catch { /* fall through to line format */ }
  const answers = {};
  let unreadable = false;
  for (const line of raw.split(/\r?\n/).map(text).filter(Boolean)) {
    const m = line.match(/^(.+?)\s*(?:=>|::)\s*(.+)$/);
    if (m) answers[text(m[1])] = text(m[2]);
    else unreadable = true;
  }
  return { answers, unreadable };
}

const pick = (record, pattern) =>
  Object.keys(record).filter((h) => h !== "__row" && pattern.test(h)).map((h) => record[h]);

export function providerFor(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.endsWith(".myworkdayjobs.com") || host.endsWith(".myworkdaysite.com")) return "workday";
    if (/(^|\.)greenhouse\.io$/.test(host)) return "greenhouse";
    if (host === "jobs.lever.co") return "lever";
    if (host === "jobs.ashbyhq.com") return "ashby";
    return "other";
  } catch {
    return "unknown";
  }
}

/** Evaluate all COI rows. Returns { eligible: [job payloads], blocked: [{opportunity_id,row,reason}] }. */
export function evaluateCOI(opportunityValues, manifestValues, { audit = false } = {}) {
  const opportunities = rowsFromValues(opportunityValues, REQUIRED_OPPORTUNITY_HEADERS);
  const manifests = rowsFromValues(manifestValues, REQUIRED_MANIFEST_HEADERS);

  const latestManifest = new Map();
  for (const m of manifests) {
    const id = text(m["Opportunity ID"]);
    if (id) latestManifest.set(id, m); // later rows supersede earlier ones
  }

  // Identities that already have an application in any form block later rows for the same role.
  const appliedIdentities = new Set();
  const appliedUrls = new Set();
  for (const o of opportunities) {
    const applied = APPLIED_VALUES.has(key(o.Applied)) || text(o["Applied At / Follow-Up"]) ||
      statusBlock(o.Status) === "BLOCK_APPLIED";
    if (applied) {
      appliedIdentities.add(identityKey(o.Company, o.Role));
      if (httpsUrl(o["Direct Source URL"])) appliedUrls.add(normalizedUrl(o["Direct Source URL"]));
    }
  }

  const eligible = [];
  const blocked = [];
  const seenIdentity = new Set();
  const seenUrl = new Set();
  const seenId = new Set();
  const block = (o, reason) => blocked.push({ opportunity_id: text(o["Opportunity ID"]), row: o.__row, reason });

  for (const o of opportunities) {
    const id = text(o["Opportunity ID"]);
    const company = text(o.Company);
    const role = text(o.Role);
    const sourceUrl = httpsUrl(o["Direct Source URL"]);
    if (!id && !company && !role && !text(o["Direct Source URL"])) continue; // blank row
    if (!id || !company || !role) { block(o, "BLOCK_INVALID_IDENTITY"); continue; }
    if (audit !== id.startsWith("AUDIT-")) { block(o, "BLOCK_AUDIT_NAMESPACE"); continue; }
    if (!sourceUrl) { block(o, "BLOCK_INVALID_SOURCE_URL"); continue; }
    if (APPLIED_VALUES.has(key(o.Applied)) || text(o["Applied At / Follow-Up"])) { block(o, "BLOCK_APPLIED"); continue; }

    const status = statusBlock(o.Status) || statusBlock(o["Package Status"]) || statusBlock(o["Conversion Stage"]);
    if (status) { block(o, status); continue; }

    if (!AUTHORIZED_VALUES.has(key(o["Application Authorization"]))) { block(o, "BLOCK_UNAUTHORIZED"); continue; }

    const identity = identityKey(company, role);
    const urlKey = normalizedUrl(sourceUrl);
    if (seenId.has(id)) { block(o, "BLOCK_DUPLICATE"); continue; }
    if (appliedIdentities.has(identity) || appliedUrls.has(urlKey)) { block(o, "BLOCK_DUPLICATE_OF_APPLIED"); continue; }
    if (seenIdentity.has(identity) || seenUrl.has(urlKey)) { block(o, "BLOCK_DUPLICATE"); continue; }

    const manifest = latestManifest.get(id);
    if (!manifest) { block(o, "BLOCK_DOCUMENTS_INCOMPLETE"); continue; }
    const gate = [manifest["Cross-Table Duplicate Gate"], manifest["Submission Gate Decision"], manifest["ATS Preflight Status"]]
      .map(key).join(" ");
    if (/block_existing_application|existing application/.test(gate)) { block(o, "BLOCK_APPLIED"); continue; }
    const gateStatus = statusBlock(gate.replace(/_/g, " "));
    if (gateStatus) { block(o, gateStatus); continue; }
    if (/\bblock|\bfail/.test(gate)) { block(o, "BLOCK_MANIFEST_GATE"); continue; }

    const resume = httpsUrl(manifest["Approved Resume"]);
    const coverRequired = !OPTIONAL_VALUES.has(key(manifest["Cover Letter Required"] ?? ""));
    const cover = httpsUrl(manifest["Approved Cover Letter"]);
    const supporting = pick(manifest, /supporting|additional doc/i).map(urlList);
    if (!resume || (coverRequired && !cover) || (text(manifest["Approved Cover Letter"]) && !cover) ||
        supporting.some((s) => s.invalid)) {
      block(o, "BLOCK_DOCUMENTS_INCOMPLETE");
      continue;
    }

    const screening = pick(manifest, /screening answers|approved answers/i).map(parseScreeningAnswers);
    const approvedAnswers = Object.assign({}, ...screening.map((s) => s.answers));

    seenId.add(id);
    seenIdentity.add(identity);
    seenUrl.add(urlKey);
    eligible.push({
      kind: "prep",
      opportunity_id: id,
      company,
      role,
      identity,
      source_url: sourceUrl,
      source_url_key: urlKey,
      provider: providerFor(sourceUrl),
      manifest_id: text(manifest["Manifest ID"]),
      source_row: o.__row,
      documents: {
        resume,
        cover_letter: cover,
        supporting: supporting.flatMap((s) => s.urls),
      },
      approved_answers: approvedAnswers,
      screening_answers_unreadable: screening.some((s) => s.unreadable),
      form_fingerprint: text(manifest["Form Fingerprint"]),
      audit,
    });
  }
  return { eligible, blocked, counts: { rows: opportunities.length, manifests: manifests.length } };
}
