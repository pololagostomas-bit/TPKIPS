// Run only against tests.test_workspace_queue --serve (synthetic database).
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const base = process.argv[2];
if(!base || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw Error('Pass the isolated test server URL');
(async () => {
 const browser = await chromium.launch({headless:true});
 const context = await browser.newContext();
 const page = await context.newPage();
 const errors=[];
 page.on('pageerror', error=>errors.push(error.message));
 const output=path.join(__dirname,'..','qa','workspace-navigation');fs.mkdirSync(output,{recursive:true});
 try{
  for(const route of ['/reception','/']){
   const reception=route==='/reception';
   for(const width of [1280,375]){
    await page.setViewportSize({width,height:850});
    await page.goto(base+route);
    await page.waitForSelector('body.unified-workspace');
    await page.waitForSelector(reception?'.queue-row':'.row',{state:'attached'});
    assert.equal(await page.locator(reception?'.queue-row':'.row').count(),reception?10:20);
    await page.waitForFunction(()=>document.querySelector('#bottomNav [aria-current="page"]')?.dataset.nav==='home');
    assert.deepEqual(await page.locator('#bottomNav button span').allTextContents(),['Inicio','Perfil','Trabajo','Más']);
    assert.equal(await page.locator('header.top button:visible').count(),0);
    assert.equal((await page.locator('#workspaceRole').innerText()).toLowerCase(),'administrador');
    assert.ok(await page.locator('#workspaceRole').isVisible(),'Role visible under brand');
    assert.ok((await page.locator('header.top').boundingBox()).height < (width>820?150:340),'Compact header');
    assert.ok((await page.locator('#search').boundingBox()).height<=45,'Search control height');
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
    assert.equal(overflow,false,'No horizontal page overflow');
    await page.getByRole('button',{name:'Más',exact:true}).click();
    await page.getByRole('heading',{name:'Administración',exact:true}).waitFor();
    assert.equal(await page.locator('.workspace-credits').count(),1);
    assert.ok((await page.locator('.workspace-credits').innerText()).includes('Desarrollado por Tomás Polo para Triton Trading S.A.'));
    for(const name of ['Cortes Excel','Usuarios','Carga picker','Reportes'])assert.equal(await page.getByRole('button',{name,exact:false}).filter({visible:true}).count(),1,name+' should appear once');
    await page.getByRole('button',{name:'Cortes Excel',exact:false}).click();
    await page.locator('#dailyDialog[open]').waitFor();
    await page.locator('#dailySource').selectOption('accounting');
    await page.locator('#dailyClose').click();
    await page.getByRole('button',{name:'Usuarios',exact:false}).click();
    await page.getByRole('heading',{name:'Usuarios y accesos',exact:true}).waitFor();
    await page.getByRole('button',{name:'Más',exact:true}).click();
    await page.getByRole('button',{name:'Carga picker',exact:false}).click();
    await page.getByRole('heading',{name:'Seguimiento de picking',exact:true}).waitFor();
    await page.getByRole('button',{name:'Perfil',exact:true}).click();
    await page.getByRole('heading',{name:'Perfil',exact:true}).waitFor();
    await page.waitForFunction(()=>document.querySelector('#content,#detail')?.lastElementChild?.classList.contains('workspace-credits'));
    await page.getByRole('button',{name:'Trabajo',exact:true}).click();
    await page.getByRole('heading',{name:'Pendientes y desempeño',exact:true}).waitFor();
    await page.locator('.work-global-summary .global-status').first().waitFor();
    const sortButton=page.locator('.sort-button').first();
    if(await sortButton.count()){await sortButton.click();assert.ok((await page.locator('.tablewrap tbody tr').first().innerText()).length>0,'Sortable work table');}
    await page.getByRole('button',{name:'Inicio',exact:true}).click();
    if(reception){
      await page.locator('#arrivalDate').fill('2026-09-09');
      await page.locator('#arrivalDateEnd').fill('2026-09-09');
      await page.waitForFunction(()=>typeof receptions!=='undefined'&&receptions.length===10&&receptions.every(r=>r.scheduled_date==='2026-09-09'));
      await page.getByRole('button',{name:'Ver lista de BL',exact:true}).click();
      await page.locator('#stateFilter').selectOption('ARRIBADO');
      await page.waitForFunction(()=>receptions.length===5&&receptions.every(r=>r.app_status==='ARRIBADO'));
      await page.getByRole('button',{name:'Inicio',exact:true}).click();
    }
    const geometry=await page.evaluate(()=>({layout:document.querySelector('main.layout').getBoundingClientRect().bottom,nav:document.querySelector('#bottomNav').getBoundingClientRect().top}));
    assert.ok(geometry.layout<=geometry.nav+2,'Footer must not cover workspace');
    await page.screenshot({path:path.join(output,(reception?'reception':'dispatch')+'-'+width+'.png')});
    console.log((reception?'Recepción':'Despacho')+' '+width+'px: queue, navigation, admin tools, profile OK');
   }
  }
  assert.deepEqual(errors,[],'Browser runtime errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
