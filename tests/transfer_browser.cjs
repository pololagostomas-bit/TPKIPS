const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],out=path.join(__dirname,'../qa/transfer');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback fixture required');
(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const viewport of [{width:1440,height:900},{width:393,height:873},{width:360,height:780},{width:320,height:640},{width:873,height:393}]){
   const context=await browser.newContext({viewport}),page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   const headers=[];page.on('request',r=>{if(r.url().includes('/api/transfer-confirmation/'))headers.push(r.headers());});
   await page.goto(base+'/transfer-confirmation#token='+'A'.repeat(43));
   await page.waitForFunction(()=>document.querySelector('#status').textContent!=='Validando enlace…');
   assert.equal(new URL(page.url()).hash,'');
   if(viewport.width===1440){
    assert.equal(await page.locator('#bl').innerText(),'QA-TRANSFER-1');
    assert.equal(await page.locator('#confirmButton').isDisabled(),true);
    const check=await page.request.post(base+'/api/transfer-confirmation/inspect',{headers:{'X-WMS-Request':'1'},data:{token:'A'.repeat(43)}});
    assert.equal((await check.json()).confirmed,false,'Opening the email must not confirm');
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.screenshot({path:path.join(out,'confirm-'+viewport.width+'.png'),fullPage:true});
   assert.deepEqual(errors,[]);assert.ok(headers.every(h=>!h.cookie&&!h.referer));
   assert.equal((await context.request.get(base+'/api/receptions')).status(),401);
   assert.equal((await context.cookies()).length,0);await context.close();
  }
  const page=await browser.newPage({viewport:{width:393,height:873}});
  await page.goto(base+'/transfer-confirmation#token='+'B'.repeat(43));
  await page.waitForFunction(()=>document.querySelector('#error').textContent);
  assert.equal(await page.locator('#request').isVisible(),false);
  await page.screenshot({path:path.join(out,'expired.png'),fullPage:true});
  await page.goto(base+'/transfer-confirmation#token='+'A'.repeat(43));
  await page.locator('#checked').check();
  await page.locator('#confirmButton').click();
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Gracias'));
  await page.screenshot({path:path.join(out,'done.png'),fullPage:true});
  await page.goto(base+'/transfer-confirmation#token='+'A'.repeat(43));
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Gracias'));
  assert.equal(await page.locator('#request').isVisible(),false);
  await page.goto(base+'/login');
  await page.locator('#username').fill('qa.reader');await page.locator('#password').fill('QA-password-only-123!');
  await page.locator('#loginForm button').click();
  await page.waitForURL(url=>!url.pathname.includes('login'));
  await page.goto(base+'/reception');await page.evaluate(()=>loadDetail(1));
  await page.getByRole('button',{name:'Ver aviso en Correos',exact:true}).click();
  await page.locator('#transferMailCenter').waitFor();
  assert.equal(await page.locator('#transferMailResult').getByText('QA-TRANSFER-1',{exact:true}).count(),1);
  await page.locator('#transferMailCenter summary').click();
  await page.locator('#transferSender').fill('sender@example.test');
  await page.locator('#transferRecipient').fill('recipient@example.test');
  await page.locator('#transferOrigin').fill('https://wms.example.test');
  await page.getByRole('button',{name:'Guardar configuración',exact:true}).click();
  await page.locator('#transferSettingsStatus').filter({hasText:'Configuración guardada'}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await page.screenshot({path:path.join(out,'admin-settings.png'),fullPage:true});
  for(const viewport of [{width:1440,height:900},{width:393,height:873},{width:375,height:812},{width:320,height:640},{width:873,height:393}]){
   await page.setViewportSize(viewport);await page.evaluate(()=>showNotifications());
   await page.locator('#transferMailCenter').waitFor();
   await page.waitForFunction(()=>$('transferMailResult')?.textContent.includes('Sesión Microsoft registrada'));
   assert.equal(await page.locator('#transferMailResult a[href="/purchase-alerts"]').count(),0,'An existing session does not prompt another authorization');
   assert.equal(await page.locator('#transferMailCenter').count(),1);
   await page.locator('#refreshTransferMail').click();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.screenshot({path:path.join(out,'mail-center-'+viewport.width+'.png'),fullPage:true});
  }
  console.log('OK: five guest viewports, fragment removed, no cookies/referrer/WMS access, explicit SAP confirmation, expiry/reuse');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
