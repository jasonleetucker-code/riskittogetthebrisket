import vm from "node:vm";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { parseArgs, summarise, failedSample, measureOnce, collectAttempt, targetVerdicts, productionAuth, authenticateProduction, productionPreflight, installBaselineDiagnostics } from "../../frontend/scripts/measure-route-baselines.mjs";
const { baselineUsefulState } = createRequire(import.meta.url)("./helpers/journey.js");

test("arguments reject vacuous or unknown runs and routes", () => {
  for (const args of [["--runs","0"],["--runs","NaN"],["--runs","1.5"],["--viewport","tablet"],["--routes","/unknown"],["--routes",""],["--routes","/trade,/trade"],["--timeout","Infinity"],["--what","1"],["--runs"]]) {
    assert.throws(() => parseArgs(args), /invalid_arguments/);
  }
  assert.equal(parseArgs(["--runs","2","--routes","/trade,/rankings"]).runs,2);
});
test("missing and auth failures cannot pass or disappear", () => {
  assert.equal(summarise([],3).valid,false);
  const report = summarise([failedSample("session_failed"),{usefulMs:20,terminalState:"useful"}],3);
  assert.equal(report.valid,false); assert.equal(report.expected,3); assert.equal(report.observed,2);
  assert.equal(report.usefulMissing,1); assert.equal(report.usefulMs.n,1);
  assert.equal(summarise([{usefulMs:null,terminalState:"unavailable"}],1).unavailable,1);
});
test("HTTP error, redirect and private exception text are rejected", async () => {
  const route={path:"/rankings"};
  assert.equal((await measureOnce({goto:async()=>({status:()=>401})},route,10)).error,"navigation_status");
  assert.equal((await measureOnce({goto:async()=>({status:()=>200}),url:()=>"http://localhost/login"},route,10)).error,"route_mismatch");
  const result=await measureOnce({goto:async()=>{throw Error("PRIVATE_TOKEN")}},route,10);
  assert.equal(result.error,"navigation_failed"); assert.ok(!JSON.stringify(result).includes("PRIVATE_TOKEN"));
});
test("rankings requires visible row and nonzero virtualized universe", async () => {
  let wait;
  const page={locator:()=>({first:()=>({waitFor:async options=>{wait=options}})}),evaluate:async()=>0};
  assert.equal(await baselineUsefulState(page,"/rankings",20),"invalid_data");
  assert.equal(wait.state,"visible");
  page.evaluate=async()=>1109;
  assert.equal(await baselineUsefulState(page,"/rankings",20),"useful");
});
test("trade control chrome alone is insufficient; missing search result fails", async () => {
  const queries=[];
  const page={locator:selector=>{
    queries.push(selector);
    const item={waitFor:async()=>{if(selector.includes("search-result"))throw Error("no data")},fill:async()=>{},first(){return this}};
    return item;
  }};
  await assert.rejects(baselineUsefulState(page,"/trade",20),/no data/);
  assert.ok(queries.some(q=>q.includes("search-result:visible")));
  assert.equal(await baselineUsefulState(page,"/unknown",20),"unsupported_predicate");
});

test("invalid useful observations and arbitrary errors fail closed", () => {
  for (const value of [NaN, Infinity, -1, null, undefined]) {
    assert.equal(summarise([{ usefulMs: value, terminalState: "useful" }], 1).valid, false);
  }
  assert.equal(summarise([{ usefulMs: 4, terminalState: "missing" }], 1).valid, false);
  assert.equal(failedSample("PRIVATE_VALUE").error, "attempt_failed");
});
test("session rejection, context failure and cleanup failure retain both requested attempts", async () => {
  let closed = 0;
  const context = { request: { post: async () => ({ ok: () => false }) }, close: async () => { closed++; } };
  const result = await collectAttempt({newContext: async () => context}, "desktop", {path: "/trade"}, 10);
  assert.equal(result.cold.error, "session_failed");
  assert.equal(result.warm.error, "session_failed");
  assert.equal(closed, 1);
  const missing = await collectAttempt({newContext: async () => { throw Error("PRIVATE"); }}, "desktop", {path: "/trade"}, 10);
  assert.equal(missing.cold.error, "attempt_failed");
  assert.equal(missing.warm.error, "attempt_failed");
  context.close = async () => { throw Error("PRIVATE"); };
  const cleanup = await collectAttempt({newContext: async () => context}, "desktop", {path: "/trade"}, 10);
  assert.equal(cleanup.cold.error, "cleanup_failed");
  assert.equal(cleanup.warm.error, "cleanup_failed");
  assert.ok(!JSON.stringify([missing, cleanup]).includes("PRIVATE"));
});

test("observed targets are separate from collection and missing attempts fail", () => {
  const sample = ms => ({ usefulMs: ms, terminalState: "useful" });
  assert.equal(summarise([sample(3001)],1).valid,true);
  assert.equal(targetVerdicts([sample(3001)],[sample(1000)],1).coldP95Within3000Ms,false);
  assert.equal(targetVerdicts([sample(3000)],[sample(1000)],1).coldP95Within3000Ms,true);
  assert.equal(targetVerdicts([sample(3000)],[sample(1001)],1).warmP95Within1000Ms,false);
  assert.equal(targetVerdicts([sample(5001)],[sample(10)],1).everyObservedUsefulWithin5000Ms,false);
  assert.equal(targetVerdicts([],[],1).everyObservedUsefulWithin5000Ms,false);
  assert.equal(targetVerdicts([sample(2)],[sample(2)],1).normalNavigationP95,null);
});
test("HTTP status is retained without a URL and hidden rows are not useful", async () => {
  const failure = await measureOnce({goto:async()=>({status:()=>503})},{path:"/rankings"},10);
  assert.equal(failure.navigationStatus,503);
  assert.equal(failure.finalUrl,undefined);
  const hidden = {locator:()=>({first:()=>({waitFor:async ({state})=>{assert.equal(state,"visible");throw Error("hidden")}})})};
  await assert.rejects(baselineUsefulState(hidden,"/rankings",10),/hidden/);
});
test("client redirect after useful probe or load is rejected", async () => {
  for (const redirectAt of [2,3]) {
    let calls = 0;
    const page = {
      goto:async()=>({status:()=>200}),
      url:()=>`http://127.0.0.1:3000/${++calls >= redirectAt ? "login" : "rankings"}`,
      locator:()=>({first:()=>({waitFor:async()=>{}})}),
      evaluate:async()=>10,
      waitForLoadState:async()=>{},
    };
    assert.equal((await measureOnce(page,{path:"/rankings"},10)).error,"route_mismatch");
  }
});

test("same pathname on a foreign origin is rejected", async () => {
  const page = {goto:async()=>({status:()=>200}),url:()=>"https://unrelated.invalid/rankings"};
  assert.equal((await measureOnce(page,{path:"/rankings"},10)).error,"route_mismatch");
});
test("sub-millisecond excess cannot be rounded into a target pass", () => {
  const sample = ms => ({usefulMs:ms,terminalState:"useful"});
  assert.equal(targetVerdicts([sample(3000.1)],[sample(2)],1).coldP95Within3000Ms,false);
  assert.equal(targetVerdicts([sample(2)],[sample(1000.1)],1).warmP95Within1000Ms,false);
  assert.equal(targetVerdicts([sample(5000.4)],[sample(2)],1).everyObservedUsefulWithin5000Ms,false);
  assert.equal(summarise([sample(3000.1)],1).usefulMs.p95,3000.1);
});

test("production cookie configuration rejects untrusted origins, malformed files and expired sessions", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "baseline-auth-"));
  const file = path.join(dir,"cookie");
  try {
    fs.writeFileSync(file,"test_token",{mode:0o600});
    const env = {PROD_ORIGIN:"https://chaseupside.com",PROD_SESSION_COOKIE_FILE:file,PROD_SESSION_EXPIRES_EPOCH:"9999"};
    assert.equal(productionAuth(env,10,100).mode,"production-cookie");
    for (const patch of [{PROD_ORIGIN:"https://unrelated.invalid"},{PROD_ORIGIN:"https://chaseupside.com/path"},{E2E_TEST_SECRET:"test"},{PROD_SESSION_EXPIRES_EPOCH:"101"},{PROD_SESSION_COOKIE_FILE:dir}]) assert.throws(()=>productionAuth({...env,...patch},10,100));
    for (const value of ["","test\nsecond","token; private", "a".repeat(4097)]) {
      fs.writeFileSync(file,value); assert.throws(()=>productionAuth(env,10,100));
    }
  } finally {fs.rmSync(dir,{recursive:true});}
});
test("production session uses real status only, disables redirects and retains auth failure", async () => {
  const auth={mode:"production-cookie",origin:"https://chaseupside.com",value:"test_token",expires:Date.now()/1000+3600};
  let cookies, requestOptions;
  const ctx={addCookies:async c=>{cookies=c},request:{post:async()=>{throw Error("test_login_forbidden")},get:async(url,options)=>{
    assert.equal(url,"https://chaseupside.com/api/auth/status");requestOptions=options;
    return {status:()=>200,body:async()=>Buffer.from(JSON.stringify({authenticated:true,authMethod:"guest_pass"}))};
  }},close:async()=>{}};
  assert.equal(await authenticateProduction(ctx,auth),true);
  assert.equal(cookies[0].secure,true);assert.equal(cookies[0].url,auth.origin);assert.equal(requestOptions.maxRedirects,0);
  ctx.request.get=async()=>({status:()=>302});
  const outcome=await collectAttempt({newContext:async()=>ctx},"desktop",{path:"/rankings"},10,auth);
  assert.equal(outcome.cold.error,"production_auth_failed");assert.equal(outcome.warm.error,"production_auth_failed");
  assert.ok(!JSON.stringify(outcome).includes("test_token"));
  ctx.request.get=async()=>({status:()=>200,body:async()=>Buffer.from('{"authenticated":true,"authMethod":"password"}')});
  assert.equal(await authenticateProduction(ctx,auth),false);
});

function diagnosticRealm(enabled = true, observerFailure = false) {
  let tick = 0;
  class FakeResponse { json(...args) { this.args = args; if (this.syncFailure) throw this.syncFailure; if (this.failure) return Promise.reject(this.failure); return this.promise; } }
  class FakeRequest { constructor(url) { this.url=url; } }
  const response = new FakeResponse();
  response.promise = Promise.resolve({private:"SECRET_SENTINEL"});
  const fetchPromise = Promise.resolve(response);
  let nativeCalls = 0;
  const nativeFetch = function (...args) { nativeCalls++; this.capturedArgs = args; if (nativeFetch.failure) throw nativeFetch.failure; return fetchPromise; };
  let observer;
  class Observer {
    constructor(callback) {this.callback=callback;this.pending=[];observer=this;}
    observe() { if (observerFailure) throw Error("SECRET_SENTINEL"); }
    takeRecords() {if (observerFailure) throw Error("failed observer used"); const entries=this.pending;this.pending=[];return entries;}
  }
  const context = vm.createContext({URL,Request:FakeRequest,Response:FakeResponse,PerformanceObserver:Observer,
    location:{origin:"https://chaseupside.com"},performance:{now:()=>++tick/10,addEventListener:()=>{}},fetch:nativeFetch});
  const before = FakeResponse.prototype.json;
  vm.runInContext(`(${installBaselineDiagnostics.toString()})(${enabled})`, context);
  return {context,response,fetchPromise,nativeFetch,before,FakeResponse,get nativeCalls(){return nativeCalls;},get observer(){return observer;}};
}

test("diagnostics default off leaves native functions untouched", () => {
  const realm=diagnosticRealm(false);
  assert.equal(realm.context.fetch,realm.nativeFetch);
  assert.equal(realm.FakeResponse.prototype.json,realm.before);
  assert.equal(realm.context.__baselineDiagnosticsSnapshot,undefined);
  assert.equal(parseArgs([]).diagnostics,false);
  assert.throws(()=>parseArgs(["--diagnostics","yes"]),/invalid_arguments/);
});

test("diagnostics preserve fetch and JSON promise identities, values, receiver and privacy", async () => {
  const r=diagnosticRealm();
  const promise=r.context.fetch("https://chaseupside.com/api/dynasty-data?view=array&private=SECRET_SENTINEL",{headers:{secret:"SECRET_SENTINEL"}});
  assert.equal(promise,r.fetchPromise);
  assert.equal(await promise,r.response);
  const json=r.response.json("native_argument");
  assert.equal(json,r.response.promise);
  assert.equal((await json).private,"SECRET_SENTINEL");
  assert.equal(r.response.args[0],"native_argument");
  r.observer.pending=[{name:"https://chaseupside.com/api/data?view=full&secret=SECRET_SENTINEL",startTime:1.1,responseStart:2.2,responseEnd:3.3,encodedBodySize:123,decodedBodySize:456}];
  const data=r.context.__baselineDiagnosticsSnapshot();
  assert.equal(r.nativeCalls,1);assert.equal(data.events[0].category,"data");assert.equal(data.events[0].view,"array");
  assert.equal(data.resources[0].receipt,3.3);assert.equal(data.resources[0].view,"full");
  assert.equal(data.pendingFetch,0);assert.equal(data.pendingJson,0);
  assert.ok(!JSON.stringify(data).includes("SECRET_SENTINEL"));
  assert.ok(!JSON.stringify(data).includes("https:"));
  assert.equal(data.jsonDurationMeaning,"body_plus_parse_plus_scheduling");
});

test("diagnostics preserve rejected JSON reason and enforce event/resource bounds", async () => {
  const r=diagnosticRealm();await r.context.fetch("/api/auth/status");
  const error=Error("SECRET_SENTINEL");r.response.failure=error;
  await assert.rejects(r.response.json(),value=>value===error);
  r.response.failure=null;
  for(let i=0;i<300;i++) await r.context.fetch("/api/unknown?secret=SECRET_SENTINEL");
  r.observer.pending=Array.from({length:600},()=>({name:"https://external.invalid/SECRET_SENTINEL",startTime:1,responseStart:2,responseEnd:3,encodedBodySize:0,decodedBodySize:0}));
  const data=r.context.__baselineDiagnosticsSnapshot();
  assert.equal(data.events.length,512);assert.ok(data.dropped>0);
  assert.equal(data.resources.length,512);assert.equal(data.resourceDropped,88);
  assert.ok(!JSON.stringify(data).includes("SECRET_SENTINEL"));
});

test("diagnostics preserve synchronous throw identity and classify unknown views without text", () => {
  const r=diagnosticRealm();const error=Error("SECRET_SENTINEL");r.nativeFetch.failure=error;
  assert.throws(()=>r.context.fetch("/api/data?view=SECRET_SENTINEL"),value=>value===error);
  r.response.syncFailure=error;
  assert.throws(()=>r.response.json(),value=>value===error);
  const data=r.context.__baselineDiagnosticsSnapshot();
  assert.equal(data.events[0].view,"unknown");assert.equal(data.pendingFetch,0);assert.equal(data.pendingJson,0);
  assert.equal(data.unattributedJson,1);assert.ok(!JSON.stringify(data).includes("SECRET_SENTINEL"));
});

test("diagnostic missing resource timings are explicit and workflow opt-in defaults off", () => {
  const r=diagnosticRealm();
  r.observer.pending=[{name:"/api/data?view=unrecognized",startTime:NaN,responseStart:0,responseEnd:0,encodedBodySize:0,decodedBodySize:0}];
  const data=r.context.__baselineDiagnosticsSnapshot();
  assert.equal(data.invalid,1);assert.equal(data.resourceTimingUnavailable,1);assert.equal(data.resources[0].start,null);
  assert.equal(data.resources[0].view,"unknown");
  const workflow=fs.readFileSync(new URL("../../.github/workflows/v1-authenticated-verification.yml",import.meta.url),"utf8");
  assert.match(workflow,/baseline_diagnostics:[\s\S]*?type: boolean[\s\S]*?default: false/);
  assert.ok(workflow.includes('--diagnostics "$BASELINE_DIAGNOSTICS"'));
});

test("live user state endpoint is settings, including private query suppression", async () => {
  const r=diagnosticRealm();await r.context.fetch("/api/user/state?owner=SECRET_SENTINEL");
  const snapshot=r.context.__baselineDiagnosticsSnapshot();
  assert.equal(snapshot.events[0].category,"settings");
  assert.ok(!JSON.stringify(snapshot).includes("SECRET_SENTINEL"));
});
test("resource observer initialization failure is unavailable without reading failed observer", () => {
  const r=diagnosticRealm(true,true);
  const snapshot=r.context.__baselineDiagnosticsSnapshot();
  assert.equal(snapshot.resourceObserverAvailable,false);
  assert.equal(snapshot.invalid,1);
  assert.equal(snapshot.resources.length,0);
  assert.ok(!JSON.stringify(snapshot).includes("SECRET_SENTINEL"));
});


test("production preflight classifies only fixed outcomes and numeric statuses", async () => {
  const auth = {mode: "production-cookie", origin: "https://chaseupside.com", value: "SECRET_SENTINEL", expires: Date.now()/1000 + 3600};
  const cases = [
    [429, "SECRET_SENTINEL", "http_status"],
    [502, "SECRET_SENTINEL", "http_status"],
    [200, "x".repeat(8193), "body_oversize"],
    [200, "SECRET_SENTINEL", "invalid_json"],
    [200, "null", "invalid_shape"],
    [200, "[]", "invalid_shape"],
    [200, '{"authenticated":false,"private":"SECRET_SENTINEL"}', "unauthenticated"],
    [200, '{"authenticated":true,"authMethod":"SECRET_SENTINEL"}', "wrong_method"],
    [200, '{"authenticated":true,"authMethod":"guest_pass"}', "accepted"],
  ];
  for (const [status, body, outcome] of cases) {
    let calls = 0;
    const ctx = {addCookies: async()=>{}, request:{get:async()=>{ calls++; return {status:()=>status,body:async()=>Buffer.from(body)}; }},close:async()=>{}};
    const result = await productionPreflight(ctx,auth);
    assert.deepEqual(result,{ok:outcome === "accepted",outcome,httpStatus:status});
    assert.equal(calls,1);
    assert.ok(!JSON.stringify(result).includes("SECRET_SENTINEL"));
    if (!result.ok) {
      const pair = await collectAttempt({newContext:async()=>ctx},"mobile",{path:"/trade"},10,auth);
      for (const sample of [pair.cold,pair.warm]) {
        assert.equal(sample.error,"production_auth_failed");
        assert.deepEqual(sample.authPreflight,result);
      }
      assert.equal(calls,2); // One request for each preflight, no hidden retry.
    }
  }
  const expired = await productionPreflight({addCookies:async()=>{throw Error("must_not_call")}}, {...auth,expires:0});
  assert.deepEqual(expired,{ok:false,outcome:"expired",httpStatus:null});
  const network = {addCookies:async()=>{},request:{get:async()=>{throw Error("SECRET_SENTINEL")}},close:async()=>{}};
  assert.deepEqual(await productionPreflight(network,auth),{ok:false,outcome:"transport_failure",httpStatus:null});
  const failed = await collectAttempt({newContext:async()=>network},"mobile",{path:"/trade"},10,auth);
  assert.equal(failed.cold.authPreflight.outcome,"transport_failure");
  assert.equal(failed.warm.error,"production_auth_failed");
  assert.ok(!JSON.stringify(failed).includes("SECRET_SENTINEL"));
  const bodyFailure = {addCookies:async()=>{},request:{get:async()=>({status:()=>200,body:async()=>{throw Error("SECRET_SENTINEL")}})}};
  assert.deepEqual(await productionPreflight(bodyFailure,auth),{ok:false,outcome:"transport_failure",httpStatus:200});
});
