"""Print geometry: one small English notice per real sticker, no barcode overlap."""
import contextlib,importlib.util,io,unittest


@unittest.skipUnless(importlib.util.find_spec('playwright'),'Optional real-browser QA runtime required')
class LabelInternalUseTests(unittest.TestCase):
    def setUp(self):
        from tests.test_dispatch_stage_history import DispatchStageHistoryTests
        self.ui=DispatchStageHistoryTests();self.addCleanup(self.ui.doCleanups);self.ui.setUp()

    def test_notice_fits_receipt_inventory_and_each_location_half(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            page,errors,posts=self.ui.page('OV','picker')
            page.add_script_tag(url=self.ui.base+'/assets/reception-labels.js')
            page.add_script_tag(url=self.ui.base+'/assets/location-labels.js')
            page.evaluate('WmsReceptionLabels.loadEngine()')
            page.context.route('**/api/inventory/brand-logo?*',lambda r:r.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="180" height="80"><text y="40" font-size="25">QA LOGO</text></svg>'))
            page.context.on('page',lambda p:p.on('pageerror',lambda error:errors.append(str(error))))
            for kind,count,selector,button in [('receipt',2,'.sticker','#printLabels'),('inventory',2,'.sticker','#printLabels'),('location',3,'.location-label','#printLocationLabels')]:
                for width in (1366,320):
                    with self.subTest(kind=kind,width=width):
                        html=page.evaluate('''async kind=>{
                          const logo='/api/inventory/brand-logo?brand=HYUNDAI&v='+'a'.repeat(64);
                          const item={np:'QA / ARTICLE-1234',quantity:2,ov:'810001',customer:'CLIENTE DE PRUEBA',description:'REPUESTO DE PRUEBA',location:'01-01-A-01-01',brand:'HYUNDAI',logo};
                          let html;
                          if(kind==='receipt')html=WmsReceptionLabels.documentHtml({bl_awb:'QA-BL'},[item,{...item,quantity:3}]);
                          if(kind==='inventory')html=WmsReceptionLabels.inventoryDocumentsHtml([{item_code:item.np,description:item.description,stock_qty:2,default_location:item.location,label_brand:'HYUNDAI',brand_logo_url:logo},{item_code:'QA-NO-STOCK',description:'Repuesto QA',stock_qty:0,label_brand:'HYUNDAI',brand_logo_url:logo}]);
                          if(kind==='location')html=await WmsLocationLabels.documentHtml(['01-01-A-01-01','01-02-A-01-01','01-03-A-01-01'],logo.replace('HYUNDAI','TRITON'));
                          return html;
                        }''',kind)
                    popup=page.context.new_page();popup.set_viewport_size({'width':width,'height':873});popup.set_content(html)
                    expect(popup.locator(button)).to_be_enabled(timeout=10000)
                    self.assertEqual(popup.locator('.label-internal-use').count(),count)
                    result=popup.locator(selector).evaluate_all('''labels=>labels.map(label=>{
                      const note=label.querySelector('.label-internal-use'),matrix=label.querySelector('.datamatrix'),a=note.getBoundingClientRect(),b=label.getBoundingClientRect(),c=matrix.getBoundingClientRect();
                      return {text:note.textContent,lang:note.lang,font:parseFloat(getComputedStyle(note).fontSize),fits:label.dataset.fits,
                        inside:a.left>=b.left-.1&&a.right<=b.right+.1&&a.top>=b.top-.1&&a.bottom<=b.bottom+.1,
                        clipped:note.scrollWidth>note.clientWidth+1||note.scrollHeight>note.clientHeight+1,
                        overlap:a.left<c.right&&a.right>c.left&&a.top<c.bottom&&a.bottom>c.top};
                    })''')
                    for item in result:
                        self.assertEqual(item['text'],'* For Triton Trading internal use only.')
                        self.assertEqual(item['lang'],'en');self.assertLessEqual(item['font'],9)
                        self.assertTrue(item['inside']);self.assertFalse(item['clipped']);self.assertFalse(item['overlap'])
                        self.assertEqual(item['fits'],'true')
                    self.assertFalse(popup.evaluate('document.documentElement.scrollWidth>innerWidth+1'))
                    popup.close()
            self.assertEqual(errors,[]);self.assertEqual(posts,[])


if __name__=='__main__':unittest.main()
