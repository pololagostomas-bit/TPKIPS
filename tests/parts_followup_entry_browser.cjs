const {chromium}=require('playwright'),assert=require('node:assert/strict');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Synthetic loopback fixture required');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 for(const width of [320,393,1366]){
  const page=await browser.newPage({viewport:{width,height:873}});page.setDefaultTimeout(7000);
  await page.goto(base+'/login');await page.locator('#username').fill('qa.reader');await page.locator('#password').fill('QA-password-only-123!');
  await page.locator('#loginForm button').click();await page.waitForURL(url=>url.pathname!='/login');await page.goto(base+'/reception');
  await page.locator('[data-nav="profile"]').click();await page.getByRole('button',{name:'Herramientas y opciones',exact:true}).click();
  await page.getByRole('button',{name:'Seguimiento de BL',exact:true}).click();await page.waitForURL('**/parts-followup');
  await page.locator('#followupStatus').filter({hasText:'BL con llegada registrada'}).waitFor();
  assert.equal(await page.locator('#backWms').isVisible(),true);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await page.close();console.log('live followup entry '+width+'px OK');
 }
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1});
