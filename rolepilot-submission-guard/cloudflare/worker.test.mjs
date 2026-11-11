import test from 'node:test';import assert from 'node:assert/strict';import worker from './worker.js';const base='https://rolepilot-staging-guard.drivyn-ai-innovations.workers.dev';const p={opportunity:'qa1',employer:'Example',role:'Tester',requisition:'req1',url:'https://jobs.example.com/req1',approved:true};function env(duplicate=false){return {API_TOKEN:'api',APPROVER_TOKEN:'approver',DB:{prepare(sql){return {bind(){return {first:async()=>sql.includes('submission_reservations')&&duplicate?{id:1}:null,run:async()=>({meta:{changes:1}})}}}}}}}async function call(path,body=p,auth='api',duplicate=false){const req=new Request(base+path,{method:'POST',headers:{authorization:'Bearer '+auth,'content-type':'application/json'},body:JSON.stringify(body)});const res=await worker.fetch(req,env(duplicate));return {status:res.status,data:await res.json()}}test('health disables submissions',async()=>{const res=await worker.fetch(new Request(base+'/health'),env());assert.equal((await res.json()).submissions_enabled,false)});test('execution always blocked',async()=>{const r=await call('/api/execute');assert.equal(r.status,403);assert.equal(r.data.reason,'LIVE_SUBMISSION_DISABLED')});test('plan requires auth',async()=>assert.equal((await call('/api/plan',p,'bad')).status,401));test('assisted fallback',async()=>{const r=await call('/api/plan');assert.equal(r.data.mode,'ASSISTED');assert.equal(r.data.submissions_enabled,false)});test('duplicate blocked',async()=>assert.equal((await call('/api/plan',p,'api',true)).status,409));test('caller approval does not grant access',async()=>assert.equal((await call('/api/preflight')).data.reason,'VERIFIED_APPROVAL_REQUIRED'));test('invalid URL blocked',async()=>assert.equal((await call('/api/plan',{...p,url:'javascript:bad'})).status,422));test('grant requires separate credential',async()=>assert.equal((await call('/api/approval/grant',p,'api')).status,401));test('grant requires explicit confirmation',async()=>assert.equal((await call('/api/approval/grant',p,'approver')).status,403));
test("Ashby sandbox requires enablement and authentication and leaves execution locked", async () => {
  const endpoint = "https://rolepilot.example/api/sandbox/ashby";
  const request = (token) => new Request(endpoint, { method: "POST", headers: { authorization: "Bearer " + token } });
  assert.equal((await worker.fetch(request("test"), { API_TOKEN: "test" })).status, 403);
  const env = { API_TOKEN: "test", ASHBY_SANDBOX_ENABLED: "true" };
  assert.equal((await worker.fetch(request("wrong"), env)).status, 401);
  const response = await worker.fetch(request("test"), env);
  assert.equal(response.status, 201);
  const body = await response.json();
  assert.equal(body.decision, "SANDBOX_RECEIPT");
  assert.equal(body.receipt.sandbox, true);
  assert.match(body.receipt.receiptId, /^test-/);
  assert.equal(body.submissions_enabled, false);
  assert.equal((await worker.fetch(new Request("https://rolepilot.example/api/execute", { method: "POST" }), env)).status, 403);
});
