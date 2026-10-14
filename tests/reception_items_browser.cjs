// Run only against a fresh support_reception_items_server.py.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Disposable loopback fixture required');
const output = path.join(__dirname, '../qa/reception-items');
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true, channel:process.env.WMS_QA_BROWSER_CHANNEL || 'msedge'});
  const errors = [];
  try {
    for (const viewport of [{width:1440,height:900},{width:393,height:873},
                           {width:375,height:812},{width:360,height:780},{width:873,height:393}]) {
      const context = await browser.newContext({viewport, reducedMotion:'reduce'});
      await context.addInitScript(() => {
        window.print = () => {};
        if (window === window.top && 'serviceWorker' in navigator)
          navigator.serviceWorker.register = async () => undefined;
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', dialog => dialog.accept());
      await page.goto(base + '/reception');
      await page.waitForFunction(() => document.querySelector('#user')?.value);
      await page.evaluate(() => loadDetail(1));
      await page.locator('#countNpFilter').waitFor({state:'visible'});
      const lines = await page.evaluate(() => selected.lines.map(line => ({id:line.id,np:line.np_code})));
      const first = lines[0].id, other = lines[2].id;
      assert.equal(await page.locator('[data-count-actions]').evaluate(node=>Boolean(node.closest('details'))),false,'Save and print are outside the collapsed full list');
      assert.match(await page.locator('[data-save-physical-review]').evaluate(node=>node.nextElementSibling.textContent),/Imprimir etiquetas por NP/);
      await page.evaluate(ids => {
        document.querySelector('details:has(#countNpTable)').open = true;
        document.getElementById('qty-' + ids[0]).value = '3';
        document.getElementById('count-location-' + ids[0]).value = 'COUNT-A01';
        document.getElementById('qty-' + ids[1]).value = '2';
      }, [first, other]);
      const pagesBeforePrint=context.pages().length;
      const previousReason=await page.locator('#reason-'+first).inputValue();
      await page.locator('#reason-'+first).fill('unsaved-print-guard-'+Date.now());
      await page.evaluate(()=>printOvStickers());
      assert.equal(context.pages().length,pagesBeforePrint,'Unsaved count changes cannot be printed');
      assert.match(await page.locator('#toast').innerText(),/Guarda los cambios/);
      await page.locator('#reason-'+first).fill(previousReason);
      await page.locator('#countNpFilter').fill(' np - 001 ');
      assert.equal(await page.locator('#countNpTable tbody tr:not([hidden])').count(), 2);
      assert.match(await page.locator('#countNpFilterStatus').innerText(), /2 de 4.*1 NP/);
      const originalIds = await page.locator('#countNpTable tbody tr').evaluateAll(rows => rows.map(row => row.dataset.countLine));
      for (const query of ['np-001','none','np-001']) {
        await page.locator('#countNpFilter').fill(query);
        assert.deepEqual(await page.locator('#countNpTable tbody tr').evaluateAll(rows => rows.map(row => row.dataset.countLine)), originalIds, 'Search never adds or duplicates rows');
        assert.equal(await page.locator('#countNpTable tbody tr:visible').count(), query === 'none' ? 0 : 2, 'Hidden rows are really hidden on mobile');
      }
      assert.equal(new Set(originalIds).size, 4, 'Each source line appears once');
      assert.equal(await page.locator('#countNpFilter').count(), 1);
      assert.equal(await page.locator('#scanReceptionNp').count(), 1);
      assert.equal(await page.locator('#countNpTable th').filter({hasText:/^IP$/}).isVisible(),false);
      assert.ok(!(await page.locator('#countNpTable tbody').innerText()).includes('Línea'));
      assert.equal(await page.locator('#qty-' + other).inputValue(), '2', 'Filter retains hidden quantity');
      assert.equal(await page.locator('#count-location-' + first).inputValue(), 'COUNT-A01');
      await page.locator('#countNpFilter').fill('none');
      assert.equal(await page.locator('#countNpTable tbody tr:not([hidden])').count(), 0);
      assert.match(await page.locator('#countNpFilterStatus').innerText(), /0 de 4/);
      // This suite exercises editing/filtering after the required reads; fast Enter has its own suite.
      await page.evaluate(async()=>{
        for(const line of selected.lines){
          const response=await api(shipmentUrl('/lines/'+line.id),{method:'POST',body:{scan_np:true,
            received_qty:Number(document.getElementById('qty-'+line.id).value),
            count_location:document.getElementById('count-location-'+line.id).value}});
          if(!response.ok)throw Error('Fixture NP read failed');
        }
        await loadDetail(1,true);
      });
      const reviewDone = page.waitForResponse(response => new URL(response.url()).pathname === '/api/receptions/1' && response.request().method() === 'GET');
      await page.locator('[data-save-physical-review]').click();
      await reviewDone;
      await page.waitForFunction(() => document.querySelector('#toast')?.textContent === 'Revisión completa guardada');
      assert.equal(await page.evaluate(() => selected.lines[0].attention_verified_qty), 3);
      assert.equal(await page.evaluate(id => selected.lines.find(line => line.id === id).attention_verified_qty, other), 2);
      assert.equal(await page.locator('#countNpFilter').inputValue(), 'none', 'Filter survives save');
      await page.locator('#countNpFilter').fill('');
      await page.evaluate(()=>WmsNpScan.review('NP-001'));
      await page.locator('.np-match').nth(1).locator('summary').click();
      await page.locator('#receptionNpScanResult button').nth(1).click();
      await page.locator('#receptionNpQuantity').fill('4');
      await page.locator('#receptionNpLocation').fill('SCANNED-OV2');
      await page.locator('#receptionNpSave').click();
      await page.waitForFunction(() => document.querySelector('#receptionNpScanResult')?.textContent.includes('NP guardado'));
      assert.equal(await page.locator('#count-location-' + lines[1].id).inputValue(), 'SCANNED-OV2');
      assert.equal(await page.locator('#count-location-' + first).inputValue(), 'COUNT-A01', 'Duplicate NP uses chosen OV only');
      const detailResponse = await page.request.get(base + '/api/receptions/1', {headers:{'X-User':'demo.admin','X-Role':'ADMINISTRADOR'}});
      const detail = await detailResponse.json();
      assert.equal(detail.lines[1].final_location, 'SCANNED-OV2');
      const countPopupPromise=page.waitForEvent('popup');
      await page.evaluate(()=>printOvStickers());
      const countPopup=await countPopupPromise;
      await countPopup.waitForFunction(()=>document.querySelector('#printLabels')&&!document.querySelector('#printLabels').disabled);
      assert.equal(await countPopup.locator('.datamatrix').count(),3);
      assert.equal(await countPopup.locator('.location-box').nth(1).innerText(),'SCANNED-OV2','Count labels use saved individual NP changes, not the stale selected snapshot');
      await countPopup.close();
      await page.screenshot({path:path.join(output, 'count-' + viewport.width + '.png')});
      await page.evaluate(() => loadDetail(4));
      assert.equal(await page.locator('#countNpFilter').inputValue(), '', 'Filter belongs to its BL');
      await page.evaluate(() => loadDetail(3));
      await page.locator('#locationNpFilter').waitFor({state:'visible'});
      assert.equal(await page.locator('#locationNpTable input:not([type=checkbox])').count(), 0, 'Location is readonly');
      assert.equal(await page.locator('#locationNpTable tbody tr').count(), 4, 'Existing planned-line confirmation policy retained');
      await page.locator('#locationNpFilter').fill('np-nostock');
      assert.equal(await page.locator('#locationNpTable tbody tr:not([hidden])').count(), 1);
      assert.equal(await page.locator('#locationNpTable tbody tr:not([hidden]) .np-location-value').innerText(), '');
      await page.getByRole('button', {name:'Confirmar ubicaciones', exact:true}).click();
      await page.locator('#toast.show').filter({hasText:'Ubicaciones confirmadas'}).waitFor();
      await page.waitForFunction(() => selected.lines.filter(line => line.location_attention_required).every(line => line.final_location_confirmed));
      const forbidden = await page.request.post(base + '/api/receptions/3/location-lines', {
        headers:{'X-User':'demo.admin','X-Role':'ADMINISTRADOR'},
        data:{locations:[{line_id:9,final_location:'FORBIDDEN',confirmed:true}]}
      });
      assert.equal(forbidden.status(), 403, 'Admin cannot replace count location in this stage');
      await page.locator('#locationNpFilter').fill('');
      await page.waitForFunction(() => document.querySelectorAll('#locationNpTable tbody tr:not([hidden])').length === 4);
      await page.screenshot({path:path.join(output, 'location-' + viewport.width + '.png')});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'No horizontal page overflow');
      for (const selector of ['#locationNpFilter','#locationNpTable .np-location-value']) {
        const box = await page.locator(selector).first().boundingBox();
        assert.ok(box && box.height >= 43.5, selector + ' readable/touch height');
      }
      if (viewport.width === 375) {
        await page.addStyleTag({content:'body.reader-ui input, body.reader-ui label, body.reader-ui td, body.reader-ui button {font-size:24px !important;line-height:1.5 !important}'});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'Large text stays within mobile viewport');
        const fits = await page.locator('#locationNpTable .np-location-value').evaluateAll(nodes => nodes.every(el => el.scrollWidth <= el.clientWidth + 1));
        assert.ok(fits, 'Destinations remain readable with enlarged text');
        await page.screenshot({path:path.join(output, 'location-large-text-375.png')});
      }
      await page.evaluate(() => loadDetail(2));
      const popupPromise = page.waitForEvent('popup');
      await page.evaluate(() => printOvStickers());
      const popup = await popupPromise;
      popup.on('pageerror', error => errors.push(error.message));
      await popup.waitForLoadState();
      await popup.waitForFunction(() => !document.querySelector('#printLabels')?.disabled);
      const labels = await popup.locator('.sticker').allTextContents();
      assert.equal(labels.length, 3, 'Only current attention counts, separate duplicate OV labels');
      assert.ok(labels[0].includes('# OV') && labels[0].includes('QA-OV-1') && labels[0].includes('Cliente uno & mantenimiento'));
      assert.ok(labels[1].includes('QA-OV-2') && labels[1].includes('Cliente dos'));
      assert.ok(labels[0].includes('BIN-QA-OV-1'));
      assert.equal(await popup.locator('.location-box').nth(2).innerText(), '', 'No-stock handwritten location box');
      assert.ok(labels.every(label => !label.includes('Sin ubicación') && !label.includes('POR DEFINIR')));
      assert.equal(await popup.locator('.barcode').count(), 3);
      const geometry = await popup.evaluate(() => ({
        background:getComputedStyle(document.body).backgroundColor,
        fits:[...document.querySelectorAll('.sticker,.np,.customer strong,.location-box')].every(el => el.scrollWidth <= el.clientWidth + 1),
        boxes:[...document.querySelectorAll('.location-box')].map(el => el.getBoundingClientRect().height)
      }));
      assert.equal(geometry.background, 'rgb(255, 255, 255)');
      assert.ok(geometry.fits, 'Long customer and NP fit without truncation');
      assert.ok(geometry.boxes.every(height => height >= 26), 'Compact handwriting box remains at least 7mm');
      await popup.screenshot({path:path.join(output, 'stickers-' + viewport.width + '.png'), fullPage:true});
      if (viewport.width === 1440) await popup.pdf({path:path.join(output,'stickers.pdf'),format:'A4',printBackground:true});
      await context.close();
      console.log('Count, NP filters, readonly location and stickers OK at ' + viewport.width);
    }
    assert.deepEqual(errors, [], 'No browser exceptions');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
