import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { parseArgs, summarise, failedSample, measureOnce, collectAttempt, targetVerdicts, productionAuth, authenticateProduction } from "../../frontend/scripts/measure-route-baselines.mjs";
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
  assert.equal(await baselineUsefulState(page,"/league",20),"unsupported_predicate");
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
