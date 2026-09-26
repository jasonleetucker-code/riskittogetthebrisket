import test from 'node:test';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {chromium} from 'playwright';
import {parseArgs,collectAttempt,targetVerdicts} from '../../frontend/scripts/measure-route-baselines.mjs';
const {routeUsefulSnapshot,baselineUsefulState}=createRequire(import.meta.url)('./helpers/journey.js');

test('public profile cannot admit a private route',()=>{
 assert.equal(parseArgs(['--auth','public','--routes','/league']).auth,'public');
 assert.throws(()=>parseArgs(['--auth','public','--routes','/game-day']));
});
test('DOM predicate is executable',()=>assert.equal(typeof routeUsefulSnapshot,'function'));

const stats=(values=['0','0','0','0','0'])=>`<main><button id="league-tab-overview" aria-selected="true">Overview</button><div id="league-panel-overview" role="tabpanel"><section class="league-card"><h2>At a glance</h2>${['Seasons','Managers','Trades','Waivers','Scored weeks'].map((label,i)=>`<div class="ds-stat"><span class="ds-stat__label">${label}</span><span class="ds-stat__value">${values[i]}</span></div>`).join('')}</section></div></main>`;
const game=(mode='Live', cells='<td><span>0.0</span></td><td><span>100.0</span></td><td><span>50%</span></td>')=>`<main><div data-game-day-ready="true" data-game-day-team="fixture"><section aria-labelledby="game-day-hero-title"><span>${mode}</span><span id="game-day-hero-title">Week 3 · 2026</span><table><thead><tr><th>Team</th>${mode==='Upcoming'?'':'<th>'+ (mode==='Final'?'Final score':'Score now')+'</th>'}${mode==='Final'?'<th>Result</th>':'<th>Projected finish</th><th>Win chance</th>'}</tr></thead><tbody><tr><th scope="row"><span>Selected team</span><span>Fixture</span></th>${cells}</tr></tbody></table></section></div></main>`;

test('actual browser DOM refuses shells/missing/wrong tab and accepts real zero public values',async()=>{
 const browser=await chromium.launch({executablePath:process.env.PW_CHROMIUM_PATH || (fs.existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe') ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : undefined)});
 try {const page=await browser.newPage();
 for(const [html,state] of [
 ['<main><h1>League</h1></main>','pending'],[stats(),'useful'],[stats(['1','—','0','0','0']),'pending'],
 [stats().replace('aria-selected="true"','aria-selected="false"'),'pending'],
 [stats().replace('role="tabpanel"','role="tabpanel" hidden'),'pending'],
 ['<main><p class="empty-state-title">League data unavailable</p></main>','unavailable'],
 [stats().replace('<button id="league-tab-overview" aria-selected="true">Overview</button>','<select id="league-section-select"><option value="overview">Overview</option></select>'),'useful'],
 ]){await page.setContent(html);assert.equal((await page.evaluate(routeUsefulSnapshot,'/league')).state,state);}
 }finally{await browser.close();}
});
test('actual Game Day DOM distinguishes scores, forecast, pending, final and no-team',async()=>{
 const browser=await chromium.launch({executablePath:process.env.PW_CHROMIUM_PATH || (fs.existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe') ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : undefined)});
 try{const page=await browser.newPage();
 for(const [html,state,detail] of [
 [game(),'useful','live_score_and_forecast'],
 [game('Live','<td><span>0.0</span></td><td colspan="2"><span>Computing…</span></td>'),'partial','live_score_only'],
 [game('Upcoming','<td colspan="2"><span>Computing…</span></td>'),'pending','data_pending'],
 [game('Upcoming','<td><span>0.0</span></td><td><span>0%</span></td>'),'useful','pregame_forecast'],
 [game('Upcoming','<td><span>Unavailable</span></td><td><span>Unavailable</span></td>'),'unavailable','forecast_unavailable'],
 [game('Final','<td><span>0.0</span></td><td><span>WIN</span></td>'),'useful','final_score'],
 [game('Final','<td><span>0.0</span></td><td><span>—</span><span>Result unavailable</span></td>'),'partial','final_incomplete'],
 [game('Final','<td><span>Unavailable</span></td><td><span>—</span></td>'),'unavailable','final_unavailable'],
 ['<main><h3>No team selected</h3></main>','unavailable','team_required'],
 [game().replace('data-game-day-team="fixture"','data-game-day-team=""'),'pending','data_pending'],
 ]){await page.setContent(html);const r=await page.evaluate(routeUsefulSnapshot,'/game-day');assert.equal(r.state,state,detail);assert.equal(r.detail,detail);}
 }finally{await browser.close();}
});
test('public league installs no cookies and performs no auth request',async()=>{
 let preflights=0,closed=0;
 const ctx={request:{get:()=>{preflights++;},post:()=>{preflights++;}},addCookies:()=>{preflights++;},newPage:async()=>({goto:async()=>{throw Error('no network fixture');}}),close:async()=>{closed++;}};
 const result=await collectAttempt({newContext:async()=>ctx},'desktop',{path:'/league'},10,{mode:'production-cookie',origin:'https://chaseupside.com',value:'SECRET'});
 assert.equal(preflights,0);assert.equal(closed,1);assert.equal(result.cold.error,'navigation_failed');
 assert.ok(!JSON.stringify(result).includes('SECRET'));
});
test('honest unavailable can meet absolute resolved ceiling without passing numeric gate',()=>{
 const sample={terminalState:'unavailable',usefulMs:null,resolvedObservedMs:10};
 const gate=targetVerdicts([sample],[sample],1);
 assert.equal(gate.everyObservedResolvedWithin5000Ms,true);
 assert.equal(gate.coldP95Within3000Ms,false);assert.equal(gate.everyObservedUsefulWithin5000Ms,false);
 assert.equal(targetVerdicts([{...sample,resolvedObservedMs:5000.1}],[sample],1).everyObservedResolvedWithin5000Ms,false);
});

test('pending wait cannot pass, delayed data resolves, wrong team/week cannot inherit readiness',async()=>{
 const browser=await chromium.launch({executablePath:process.env.PW_CHROMIUM_PATH || (fs.existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe') ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : undefined)});
 try {const page=await browser.newPage();await page.setContent('<main>Loading</main>');
 await assert.rejects(baselineUsefulState(page,'/league',70),/useful_timeout/);
 await page.evaluate(html=>setTimeout(()=>document.body.innerHTML=html,50),stats());
 assert.equal((await baselineUsefulState(page,'/league',1000)).state,'useful');
 await page.route('http://fixture.invalid/**',route=>route.fulfill({body:game(),contentType:'text/html; charset=utf-8'}));
 await page.goto('http://fixture.invalid/game-day?team=other&week=3&season=2026');
 assert.equal((await page.evaluate(routeUsefulSnapshot,'/game-day')).state,'pending');
 await page.goto('http://fixture.invalid/game-day?team=fixture&week=4&season=2026');
 assert.equal((await page.evaluate(routeUsefulSnapshot,'/game-day')).state,'pending');
 await page.goto('http://fixture.invalid/game-day?team=fixture&week=3&season=2026');
 assert.equal((await page.evaluate(routeUsefulSnapshot,'/game-day')).state,'useful');
 }finally{await browser.close();}
});


test('review regressions scope section errors and preserve partial/unavailable scores',async t=>{
 const browser=await chromium.launch({executablePath:process.env.PW_CHROMIUM_PATH || (fs.existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe') ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : undefined)});
 try {const page=await browser.newPage();
 for(const [name,path,html,state,detail] of [
 ['wrong tab error','/league','<main><button id="league-tab-history" aria-selected="true">History</button><div id="league-panel-history" role="tabpanel"><p class="empty-state-title">Section unavailable</p></div></main>','pending','data_pending'],
 ['partial score','/game-day',game('Live','<td><span>0.0</span><span>Partial — scoring missing for 2 players</span></td><td><span>100.0</span></td><td><span>50%</span></td>'),'partial','score_partial'],
 ['final unavailable','/game-day',game('Final','<td><span>Unavailable</span></td><td><span>—</span><span>Result unavailable</span></td>'),'unavailable','final_unavailable'],
 ]) await t.test(name,async()=>{await page.setContent(html);const result=await page.evaluate(routeUsefulSnapshot,path);assert.deepEqual(result,{state,detail});});
 }finally{await browser.close();}
});

test('forecast failed banner is unavailable while ordinary computing stays pending',async()=>{
 const browser=await chromium.launch({executablePath:process.env.PW_CHROMIUM_PATH || (fs.existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe') ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : undefined)});
 try {const page=await browser.newPage();
 const pending=game('Upcoming','<td colspan="2"><span>Computing…</span></td>');
 await page.setContent(pending);assert.deepEqual(await page.evaluate(routeUsefulSnapshot,'/game-day'),{state:'pending',detail:'data_pending'});
 await page.setContent(pending.replace('</section>','<div class="ds-banner"><p class="ds-banner__title">Forecast failed</p></div></section>'));
 assert.deepEqual(await page.evaluate(routeUsefulSnapshot,'/game-day'),{state:'unavailable',detail:'forecast_failed'});
 }finally{await browser.close();}
});
