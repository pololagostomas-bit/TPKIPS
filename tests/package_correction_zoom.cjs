// Read-only visual QA against the disposable arrivals fixture after its workflow test.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const base=process.argv[2];if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'});try{
 for(const viewport of [{width:320,height:740},{width:1366,height:900}]){
  const page=await browser.newPage({viewport});await page.goto(base+'/reception');await page.waitForFunction(()=>window.WmsPackageReview);
  await page.evaluate(async width=>{const rows=await(await api('/api/receptions?search=QA-ARRIVALS-'+width)).json();await loadDetail(rows.find(r=>r.bl_awb==='QA-ARRIVALS-'+width).id);},viewport.width);
  await page.locator('#packageReviewOpen').click();await page.locator('[data-package-replace]').first().click();
  await page.addStyleTag({content:'.read-correction-dialog *{font-size:28px!important;line-height:1.3!important}'});
  const clipped=await page.locator('#packageReviewDialog button:visible').evaluateAll(nodes=>nodes.filter(node=>node.scrollHeight>node.clientHeight+1).map(node=>node.textContent));
  assert.deepEqual(clipped,[],'Large text must remain inside its button');
  await page.locator('#packageCorrectionCancel').scrollIntoViewIfNeeded();const b=await page.locator('#packageCorrectionCancel').boundingBox();assert(b.x>=0&&b.x+b.width<=viewport.width&&b.y>=0&&b.y+b.height<=viewport.height);
  const dir=path.join(__dirname,'../qa/runtime/package-corrections');fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,'zoom-'+viewport.width+'.png')});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await page.locator('#packageReviewClose').scrollIntoViewIfNeeded();await page.locator('#packageReviewClose').click();
  console.log('OK large text fits correction buttons '+viewport.width);await page.close();
 }
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
