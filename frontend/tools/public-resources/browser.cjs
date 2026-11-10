// Local-only acceptance against the real public renderer and its CSP headers.
// Requires backend Python dependencies, Playwright and a Chromium installation.
const {execFileSync} = require('node:child_process');
const {createServer} = require('node:http');
const {resolve} = require('node:path');
const {existsSync} = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const repo = resolve(__dirname, '../../..');
const fixture = JSON.parse(execFileSync(process.env.BP_PYTHON || 'python3', ['-c', `
import sys,json,base64
from io import BytesIO
sys.path.insert(0,'backend')
from PIL import Image
from app.modules.projects.public_resource_page import render_gallery,PUBLIC_HEADERS
out=BytesIO();Image.new('RGB',(12,12),'gold').save(out,format='PNG')
image=base64.b64encode(out.getvalue()).decode()
snapshot=f'<h1>Residence A</h1><img src="data:image/png;base64,{image}" alt="Exterior"><img src="data:image/png;base64,{image}" alt="Interior">'
print(json.dumps({'html':render_gallery(snapshot.encode(),project_name='Ashville Park',property_name='Residence A').decode(),'headers':PUBLIC_HEADERS}))
`], {cwd: repo, encoding:'utf8'}));
(async () => {
  const server = createServer((req,res) => {res.writeHead(200,{'Content-Type':'text/html; charset=utf-8',...fixture.headers});res.end(fixture.html);});
  let browser;
  try {
    await new Promise((ok,fail) => {server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
    browser = await chromium.launch({headless:true, executablePath:process.env.BP_CHROME || (existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined)});
    for (const width of [1280,390]) {
      const context = await browser.newContext({viewport:{width,height:900}});
      const page = await context.newPage();
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      const origin=`http://127.0.0.1:${server.address().port}`;
      await page.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort());
      await page.goto(origin);
      await page.locator('.thumbnail img').first().waitFor();
      assert.equal(await page.locator('.thumbnail img').first().evaluate(img=>img.complete && img.naturalWidth>0),true);
      assert.equal(await page.locator('h1').textContent(),'Ashville Park');
      await page.locator('.thumbnail').nth(1).click();
      assert.equal(await page.locator('dialog').isVisible(),true);
      assert.equal(await page.locator('.counter').textContent(),'2 / 2');
      await page.locator('.next').click();assert.equal(await page.locator('.counter').textContent(),'1 / 2');
      await page.locator('.previous').click();assert.equal(await page.locator('.counter').textContent(),'2 / 2');
      await page.keyboard.press('ArrowRight');assert.equal(await page.locator('.counter').textContent(),'1 / 2');
      await page.keyboard.press('Escape');assert.equal(await page.locator('dialog').isVisible(),false);
      assert.equal(await page.locator('.thumbnail').nth(1).evaluate(el=>el===document.activeElement),true);
      await page.locator('.thumbnail').first().click();await page.locator('.close').click();
      assert.equal(await page.locator('dialog').isVisible(),false);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      assert.deepEqual(errors,[]);
      console.log(`PASS ${width}px: CSP, embedded images, gallery navigation, keyboard, close, focus and layout`);
      await context.close();
    }
  } finally {
    if(browser) await browser.close();
    await new Promise(ok=>server.close(ok));
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
