// Server-side Google access using a service account stored only as the Worker secret
// GOOGLE_SERVICE_ACCOUNT_JSON. Read-only scopes. Nothing here is committed with credentials.

const SCOPES = "https://www.googleapis.com/auth/spreadsheets.readonly https://www.googleapis.com/auth/drive.readonly";
let cached = { token: "", exp: 0, email: "" };

const b64url = (bytes) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64urlJson = (v) => b64url(new TextEncoder().encode(JSON.stringify(v)));

function serviceAccount(env) {
  if (!env.GOOGLE_SERVICE_ACCOUNT_JSON) throw new Error("GOOGLE_CREDENTIAL_MISSING");
  let sa;
  try { sa = JSON.parse(env.GOOGLE_SERVICE_ACCOUNT_JSON); } catch { throw new Error("GOOGLE_CREDENTIAL_INVALID"); }
  if (sa.type !== "service_account" || !sa.client_email || !sa.private_key) throw new Error("GOOGLE_CREDENTIAL_INVALID");
  return sa;
}

async function accessToken(env, fetcher = fetch) {
  const sa = serviceAccount(env);
  const now = Math.floor(Date.now() / 1000);
  if (cached.token && cached.email === sa.client_email && cached.exp - 120 > now) return cached.token;
  const pem = sa.private_key.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  const der = Uint8Array.from(atob(pem), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
  const unsigned = b64urlJson({ alg: "RS256", typ: "JWT" }) + "." +
    b64urlJson({ iss: sa.client_email, scope: SCOPES, aud: "https://oauth2.googleapis.com/token", iat: now, exp: now + 3600 });
  const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(unsigned));
  const res = await fetcher("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion: unsigned + "." + b64url(signature) }),
  });
  if (!res.ok) throw new Error("GOOGLE_AUTH_FAILED_" + res.status);
  const body = await res.json();
  cached = { token: body.access_token, exp: now + Number(body.expires_in || 3600), email: sa.client_email };
  return cached.token;
}

/** Read the Opportunities and Application Manifests tabs in one batchGet call. */
export async function readCOI(env, fetcher = fetch) {
  if (!env.COI_SHEET_ID) throw new Error("COI_SHEET_ID_MISSING");
  const token = await accessToken(env, fetcher);
  const params = new URLSearchParams({ valueRenderOption: "FORMATTED_VALUE", majorDimension: "ROWS" });
  params.append("ranges", "'Opportunities'!A1:CZ6000");
  params.append("ranges", "'Application Manifests'!A1:CZ3000");
  const res = await fetcher(
    `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(env.COI_SHEET_ID)}/values:batchGet?${params}`,
    { headers: { authorization: "Bearer " + token } },
  );
  if (res.status === 403 || res.status === 404) throw new Error("COI_SHEET_NOT_SHARED_WITH_SERVICE_ACCOUNT");
  if (!res.ok) throw new Error("COI_READ_FAILED_" + res.status);
  const { valueRanges = [] } = await res.json();
  return { opportunities: valueRanges[0]?.values || [], manifests: valueRanges[1]?.values || [] };
}

export function driveFileId(url) {
  try {
    const u = new URL(url);
    if (!/(^|\.)(google\.com)$/.test(u.hostname)) return "";
    const m = u.pathname.match(/\/d\/([\w-]{10,})/) || [null, u.searchParams.get("id")];
    return m[1] && /^[\w-]{10,}$/.test(m[1]) ? m[1] : "";
  } catch {
    return "";
  }
}

/** Stream an approved document. Google-native files are exported as PDF. */
export async function fetchDocument(env, url, fetcher = fetch) {
  const id = driveFileId(url);
  if (!id) throw new Error("DOCUMENT_NOT_ON_DRIVE");
  const token = await accessToken(env, fetcher);
  const auth = { headers: { authorization: "Bearer " + token } };
  const meta = await fetcher(`https://www.googleapis.com/drive/v3/files/${id}?fields=name,mimeType,size&supportsAllDrives=true`, auth);
  if (!meta.ok) throw new Error("DOCUMENT_NOT_SHARED_WITH_SERVICE_ACCOUNT");
  const { name, mimeType } = await meta.json();
  const native = mimeType?.startsWith("application/vnd.google-apps.");
  const res = await fetcher(native
    ? `https://www.googleapis.com/drive/v3/files/${id}/export?mimeType=application/pdf`
    : `https://www.googleapis.com/drive/v3/files/${id}?alt=media&supportsAllDrives=true`, auth);
  if (!res.ok) throw new Error("DOCUMENT_DOWNLOAD_FAILED");
  const filename = (native ? String(name).replace(/\.[a-z0-9]+$/i, "") + ".pdf" : String(name)).replace(/[^\w .()-]/g, "_");
  return { body: res.body, filename, contentType: native ? "application/pdf" : mimeType || "application/octet-stream" };
}

export function resetGoogleCache() { cached = { token: "", exp: 0, email: "" }; }
