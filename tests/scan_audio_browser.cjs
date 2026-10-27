// Real browser Web Audio, synthetic gestures only. No app data or network calls.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const {chromium} = require('playwright');

test('actual Web Audio unlocks for HID and camera gestures and recovers after suspension', async () => {
  const browser = await chromium.launch({headless:true,channel:'msedge',
    args:['--autoplay-policy=document-user-activation-required']});
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.fulfill({contentType:'text/html',body:
      '<input id="scan"><button id="camera">Camara</button>'}));
    await page.goto('http://127.0.0.1:51990/audio');
    await page.evaluate(() => {
      window.contexts=[];window.tones=[];
      const Native=window.AudioContext;
      window.AudioContext=class extends Native {
        constructor(){super();this.unlocked=this.state==='running';contexts.push(this);}
        resume(){this.unlocked=false;const attempt=super.resume();return attempt.then(()=>{this.unlocked=true;});}
        createOscillator(){
          const node=super.createOscillator(),start=node.start.bind(node);
          const set=node.frequency.setValueAtTime.bind(node.frequency);let frequency;
          node.frequency.setValueAtTime=(value,at)=>{frequency=value;return set(value,at);};
          node.start=(at)=>{tones.push({frequency,at});return start(at);};
          return node;
        }
      };
    });
    await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,'../frontend/static/scan-feedback.js'),'utf8')});
    await page.evaluate(() => {
      document.querySelector('#scan').onkeydown=e=>{if(e.key==='Enter')WmsScanFeedback.arm();};
      document.querySelector('#camera').onclick=()=>WmsScanFeedback.arm();
      WmsScanFeedback.success();
    });
    assert.equal(await page.evaluate(()=>contexts.length),0);
    await page.locator('#scan').press('Enter');
    await page.waitForFunction(()=>contexts[0]?.state==='running' && contexts[0].unlocked);
    await page.evaluate(()=>WmsScanFeedback.success());
    await page.waitForFunction(()=>tones.length===1);
    assert.equal(await page.evaluate(()=>contexts[0].state),'running');
    assert.ok(await page.evaluate(()=>tones[0].frequency>800));
    await page.evaluate(()=>contexts[0].suspend());
    await page.evaluate(()=>WmsScanFeedback.success());
    assert.equal(await page.evaluate(()=>tones.length),1);
    await page.locator('#camera').click();
    await page.waitForFunction(()=>contexts[0].state==='running' && contexts[0].unlocked);
    await page.evaluate(()=>WmsScanFeedback.error());
    await page.waitForFunction(()=>tones.length===3);
    assert.equal(await page.evaluate(()=>contexts[0].state),'running');
    assert.ok(await page.evaluate(()=>tones.slice(1).every(t=>t.frequency<400)));
    await page.evaluate(()=>Promise.all(contexts.map(c=>c.close())));
    await page.close();
  } finally {await browser.close();}
});
