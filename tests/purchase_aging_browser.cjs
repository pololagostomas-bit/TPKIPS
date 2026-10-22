// Synthetic admin UI only. No Microsoft, Excel download or real delivery.
const {chromium} = require('playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const root = path.resolve(__dirname, '..');
(async () => {
  const browser = await chromium.launch({headless:true,channel:'msedge'});
  try {
    for (const width of [320,393,1366]) {
      const context = await browser.newContext({viewport:{width,height:873},acceptDownloads:true});
      const page = await context.newPage(), errors = [];
      page.on('pageerror',e=>errors.push(e.message));
      let exports=0, mode='ok', release;
      await page.route('**/*', async route => {
        const url = new URL(route.request().url()), file = url.pathname;
        if (file==='/purchase-alerts') return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'frontend/templates/purchase-alerts.html'),'utf8')});
        if (file.startsWith('/assets/')) {
          const local=path.join(root,'frontend/static',path.basename(file));
          if (!fs.existsSync(local)) return route.abort();
          return route.fulfill({contentType:file.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(local)});
        }
        let data;
        if (file.endsWith('/status')) data={settings:{sender:'qa@contoso.test',sender_name:'QA',to:[],cc:[],excluded_sheets:[],interval_minutes:60,daily_time:'10:00',subject:'QA',new_subject:'QA',body:'QA',new_intro:'QA',enabled:false,weekdays:[0]},state:{},history:[]};
        else if (file.endsWith('/cases')) {
          if(mode==='error') return route.fulfill({status:503,contentType:'application/json',body:'{"error":"QA historial no disponible"}'});
          data={items:[{id:1,issue_type:'COT',severity:'GRAVE',status:'PENDIENTE',ip:'IP-SYNTHETIC',ov:'COT1',preliminary:'PRE1',request_date_display:'17/09/2026; 18/09/2026',sources:[{sheet:'BUYER'}],first_seen_at:'2026-10-21T10:00:00+00:00',last_seen_at:'2026-10-21T12:00:00+00:00',resolved_at:null,elapsed_hours:2}],total:51,offset:Number(url.searchParams.get('offset')||0),has_more:Number(url.searchParams.get('offset')||0)===0};
        } else if(file.endsWith('/export')) {
          exports++; if(mode==='hold') await new Promise(resolve=>{release=resolve});
          if(mode==='bad-export') return route.fulfill({status:503,contentType:'application/json',body:'{"error":"QA export no disponible"}'});
          return route.fulfill({contentType:'text/csv',body:'IP,OC\r\nIP1,PRE1\r\n'});
        } else return route.abort();
        return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
      });
      await page.goto('http://qa.test/purchase-alerts');
      await page.getByText('IP-SYNTHETIC',{exact:true}).waitFor();
      assert.match(await page.locator('#caseRows').innerText(), /GRAVE/);
      assert.match(await page.locator('#caseRows').innerText(), /2 h/);
      assert.equal(await page.locator('#caseRows [data-label="Fecha de solicitud IMP/OV"]').innerText(), '17/09/2026; 18/09/2026');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      await page.locator('#caseNext').click();
      await page.waitForFunction(()=>document.querySelector('#casePage').textContent.includes('51'));
      mode='hold';
      const download=page.waitForEvent('download');
      await page.locator('#caseExport').click();
      await page.evaluate(()=>document.querySelector('#caseExport').click());
      assert.equal(exports,1);
      release(); await download; mode='ok';
      await page.waitForFunction(()=>!document.querySelector('#caseExport').disabled);
      mode='error'; await page.locator('#caseState').selectOption('resolved');
      await page.getByText('QA historial no disponible',{exact:true}).waitFor();
      assert.equal(await page.locator('#caseRows').innerText(),'');
      mode='ok'; await page.locator('#caseState').selectOption('pending');
      await page.getByText('IP-SYNTHETIC',{exact:true}).waitFor();
      mode='bad-export'; await page.locator('#caseExport').click();
      await page.getByText('QA export no disponible',{exact:true}).waitFor();
      await page.locator('#caseTracking').scrollIntoViewIfNeeded();
      fs.mkdirSync(path.join(root,'qa/purchase-aging'),{recursive:true});
      await page.screenshot({path:path.join(root,`qa/purchase-aging/history-${width}.png`),fullPage:false});
      assert.deepEqual(errors,[]); await context.close();
    }
    console.log('OK purchase aging: 3 viewports, filters, pagination, CSV single-flight, errors and no real mail.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
