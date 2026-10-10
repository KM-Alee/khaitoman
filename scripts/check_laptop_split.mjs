// Real-data browser check of a separate static frontend and laptop backend.
// Run inside the existing e2e image with --network host, as documented in the runbook.
import { createRequire } from 'node:module';
const { chromium } = createRequire(new URL('../web/package.json', import.meta.url))('@playwright/test');
import { mkdirSync } from 'node:fs';
const browser = await chromium.launch({headless:true, args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page = await browser.newPage({viewport:{width:1366,height:900}});
const failed = [];
page.on('requestfailed', r => failed.push({url:r.url(),error:r.failure()?.errorText}));
await page.goto('http://127.0.0.1:5180', {waitUntil:'networkidle'});
const result = await page.evaluate(async () => {
  const base='http://127.0.0.1:8010';
  const get=async(path)=>{const r=await fetch(base+path,{credentials:'include'}); if(!r.ok) throw new Error(path+': '+r.status); return r.json();};
  const health=await get('/api/v2/health');
  const demo=await get('/api/v2/demo/session');
  const storedRun=await get('/api/v2/runs/'+demo.base.runs.P);
  const sse=await new Promise((resolve,reject)=>{
    const es=new EventSource(base+'/api/v2/jobs/'+storedRun.job_id+'/events',{withCredentials:true});
    const timer=setTimeout(()=>{es.close();reject(new Error('SSE event timeout'));},10000);
    for(const type of ['stage','progress','result']) es.addEventListener(type,event=>{
      clearTimeout(timer);es.close();resolve({type,event_id:JSON.parse(event.data).event_id});
    });
    es.onerror=()=>{clearTimeout(timer);es.close();reject(new Error('SSE connection failed'));};
  });
  const pilots=await get('/api/v2/pilots');
  const map=await get(`/api/v2/pilots/${demo.pilot_id}/versions/${demo.pilot_version}/map`);
  const assetPaths=[map.fields_url,map.canals_url,map.imagery?.[0]?.url,map.terrain?.url].filter(Boolean);
  const assets=[];
  for(const path of assetPaths){const r=await fetch(base+path,{credentials:'include'}); if(!r.ok)throw new Error('asset '+r.status+': '+path); assets.push({path,type:r.headers.get('content-type'),bytes:(await r.arrayBuffer()).byteLength});}
  const rejected=await fetch(base+'/api/v2/deployment-preflight-smoke',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-Contract-Version':'2.0.0','Idempotency-Key':'deployment-smoke'},body:'{}'});
  if(rejected.status!==404 || (await rejected.json()).code!=='NOT_FOUND')throw new Error('JSON 404/preflight failed');
  return {health,sse,pilots:pilots.pilots?.length,assets,demo:{pilot:demo.pilot_id,version:demo.pilot_version,season:demo.season_id}};
});
await page.goto(`http://127.0.0.1:5180/p/${result.demo.pilot}/${result.demo.version}/workspace?season=${result.demo.season}`, {waitUntil:'networkidle'});
await page.getByTestId('connection-state').first().waitFor();
if(!(await page.getByTestId('connection-state').first().getAttribute('aria-label'))?.includes('online')) throw new Error('UI backend is offline');
await page.waitForFunction(()=>document.querySelectorAll('.maplibregl-canvas').length>0);
mkdirSync('/app/evidence/screenshots',{recursive:true});
await page.screenshot({path:'/app/evidence/screenshots/laptop-split-origin.png',fullPage:true});
if(failed.some(x=>!x.error?.includes("ABORTED"))) throw new Error("Unexpected request failures: "+JSON.stringify(failed));
console.log(JSON.stringify({...result,requestsFailed:failed.filter(x=>!x.error?.includes('ABORTED')),page:page.url()},null,2));
await browser.close();
