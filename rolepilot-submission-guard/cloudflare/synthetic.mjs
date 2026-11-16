// Clearly labeled synthetic verification role. The "employer" form is served by this Worker, so a live end-to-end
// run (Sheets -> Worker -> Queue -> D1 -> runner -> Sheets) never contacts a real employer. Any click on the final
// submit control is recorded as a violation.

import { driveFileId } from "./google.mjs";
import { SYNTHETIC_PREFIX } from "./prep.mjs";
import { columnLetter as letter } from "./writeback.mjs";

export const SYNTH_ID = new RegExp(`^${SYNTHETIC_PREFIX}[0-9]{8}-[0-9]{2}$`);
export const SYNTH_COMPANY = "RolePilot Synthetic Test Co (NOT A REAL EMPLOYER)";
export const SYNTH_ROLE = "Synthetic Preparation Verification";
// Each synthetic ID gets its own role title so the duplicate gate (company + role) treats them as distinct roles.
export const SYNTH_ANSWERS = {
  "First Name": "Synthetic",
  "Email": "synthetic.applicant@example.test",
  "Are you legally authorized to work in the United States?": "Yes",
  "Will you now or in the future require sponsorship?": "No",
};

const text = (v) => String(v ?? "").trim();

/** Append one synthetic Opportunities row and one Application Manifests row. Idempotent per ID. */
export async function seedSynthetic(sheets, { id, origin, resume, cover }) {
  if (!SYNTH_ID.test(id)) throw new Error("SYNTHETIC_ID_INVALID");
  if (!driveFileId(resume) || !driveFileId(cover)) throw new Error("SYNTHETIC_DOCUMENTS_MUST_BE_DRIVE");
  const [[oh = []], [mh = []]] = await sheets.get(["'Opportunities'!1:1", "'Application Manifests'!1:1"]);
  const oCol = oh.map(text).indexOf("Opportunity ID");
  const mCol = mh.map(text).indexOf("Opportunity ID");
  if (oCol < 0 || mCol < 0) throw new Error("COI_SCHEMA_MISSING");
  const [[ids = []], [mids = []]] = await sheets.get(
    [`'Opportunities'!${letter(oCol)}:${letter(oCol)}`, `'Application Manifests'!${letter(mCol)}:${letter(mCol)}`], "COLUMNS");
  const oppExists = ids.some((v) => text(v) === id);
  const manExists = mids.some((v) => text(v) === id);

  const note = `SYNTHETIC TEST ROW created by RolePilot verification ${new Date().toISOString().slice(0, 10)}. ` +
    "Not a real role or employer; the form is hosted by the RolePilot Worker. Safe to delete after review.";
  const opp = {
    "Opportunity ID": id, Company: SYNTH_COMPANY, Role: `${SYNTH_ROLE} ${id}`, "Direct Source URL": `${origin}/synthetic/apply/${id}`,
    Status: "Ready (synthetic test)", Applied: "FALSE", "Application Authorization": "Authorized", Notes: note,
  };
  // Uses the tracker's real manifest columns: structured applicant fields (Full Name, Email, Work Authorization) plus
  // the Answer Map for the sponsorship question, so both approved-answer paths are exercised.
  const man = {
    "Manifest ID": `M-${id}`, "Created At": new Date().toISOString(), "Opportunity ID": id, Company: SYNTH_COMPANY,
    "Job Title": `${SYNTH_ROLE} ${id}`, "Official Employer/ATS URL": `${origin}/synthetic/apply/${id}`, "Source Verification": "SYNTHETIC",
    "Full Name": "Synthetic Applicant", Email: SYNTH_ANSWERS.Email, "Work Authorization": "Yes",
    "Approved Resume": resume, "Approved Cover Letter": cover,
    "Live Field Inventory / Answer Map": JSON.stringify({ "Will you now or in the future require sponsorship?": "No" }),
    "Final Submission Permission": "NOT GRANTED (synthetic preparation test)", "Exact Blocker / Next Action": note,
  };
  const rowFor = (headers, values) => headers.map((h) => values[text(h)] ?? "");
  const unmatched = (headers, values) => Object.keys(values).filter((k) => !headers.map(text).includes(k));
  if (unmatched(mh, man).some((k) => ["Opportunity ID", "Approved Resume", "Approved Cover Letter"].includes(k))) {
    throw new Error("COI_SCHEMA_MISSING");
  }
  if (!oppExists) await sheets.append("Opportunities", rowFor(oh, opp));
  if (!manExists) await sheets.append("Application Manifests", rowFor(mh, man));
  return { id, opportunity_added: !oppExists, manifest_added: !manExists,
    unmatched_opportunity_headers: unmatched(oh, opp), unmatched_manifest_headers: unmatched(mh, man) };
}

/** Multi-page synthetic employer form (contact + uploads -> screening -> review with a final submit control). */
export function syntheticPage(id) {
  const spec = JSON.stringify({ id, steps: [
    { fields: [["First Name", "text"], ["Email", "email"], ["Resume", "file"], ["Cover Letter", "file"]], button: "Next" },
    { fields: [["Are you legally authorized to work in the United States?", "select", ["", "Yes", "No"]],
               ["Will you now or in the future require sponsorship?", "select", ["", "Yes", "No"]]], button: "Next" },
    { fields: [], button: "Submit Application" },
  ] });
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="robots" content="noindex">
<title>Synthetic RolePilot form — not a real employer</title></head><body><main id="app"></main><script>
const spec=${spec};let step=0;const app=document.getElementById('app');
const post=(p,d)=>fetch(p,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id:spec.id,...d})});
function job(){app.innerHTML='<h1>${SYNTH_ROLE}</h1><p>${SYNTH_COMPANY}. Synthetic verification form.</p><a href="#apply" id="apply">Apply</a>';
 document.getElementById('apply').onclick=()=>setTimeout(render,0);}
function render(){const s=spec.steps[step];const f=document.createElement('form');f.onsubmit=e=>e.preventDefault();
 s.fields.forEach(([label,type,opts],i)=>{const id='s'+step+'f'+i;const l=document.createElement('label');l.htmlFor=id;l.textContent=label;
  let el;if(type==='select'){el=document.createElement('select');opts.forEach(o=>el.add(new Option(o,o)));}else{el=document.createElement('input');el.type=type;}
  el.id=id;el.name=label.toLowerCase().replace(/[^a-z]+/g,'_').slice(0,30);el.required=true;f.append(l,el);});
 const b=document.createElement('button');b.type='button';b.textContent=s.button;f.append(b);app.replaceChildren(f);
 b.onclick=async()=>{if(s.button!=='Next'){await post('/synthetic/final',{step});app.innerHTML='<h1>Recorded as a violation</h1>';return;}
  const v={};[...f.elements].filter(e=>e.name).forEach(e=>v[e.name]=e.type==='file'?[...e.files].map(x=>x.name+':'+x.size):!!e.value);
  await post('/synthetic/step',{step,filled:v});step+=1;render();};}
job();
</script></body></html>`;
}

/** Record step evidence (field filled flags and uploaded file names/sizes only) or a final-submit violation. */
export async function syntheticEvent(env, kind, body) {
  const id = text(body?.id);
  if (!SYNTH_ID.test(id)) return false;
  const detail = kind === "final" ? "final submit control clicked" : JSON.stringify({ step: body.step, filled: body.filled }).slice(0, 500);
  await env.DB.prepare("INSERT INTO prep_events(opportunity,event,detail,audit) VALUES (?,?,?,0)")
    .bind(id, kind === "final" ? "SUBMISSION_VIOLATION" : "SYNTHETIC_FORM_STEP", detail).run();
  return true;
}
