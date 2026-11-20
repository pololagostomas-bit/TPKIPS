"""Guide camera UI with synthetic video, disposable data and real cookie sessions."""
import contextlib
import importlib.util
import io
import unittest

from backend import app


@unittest.skipUnless(importlib.util.find_spec('playwright'),'Optional real-browser QA runtime required')
class GuideCameraTests(unittest.TestCase):
    def setUp(self):
        from tests.test_dispatch_stage_history import DispatchStageHistoryTests
        self.ui=DispatchStageHistoryTests();self.addCleanup(self.ui.doCleanups);self.ui.setUp()

    def camera(self,page):
        page.evaluate('''() => {
          navigator.mediaDevices.getUserMedia=async()=>{
            const canvas=document.createElement('canvas');canvas.width=800;canvas.height=600;
            const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,800,600);
            ctx.fillStyle='black';ctx.font='30px sans-serif';ctx.fillText('GUIA QA - FIRMAS DE PRUEBA',20,100);
            window.qaPhotoStream=canvas.captureStream(5);return qaPhotoStream;
          };
        }''')

    def test_capture_previews_and_only_saves_after_signature_confirmation(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            page,errors,posts=self.ui.page('OV','picker',393,873);self.camera(page)
            page.set_default_timeout(4000)
            page.locator('.delivery-evidence [data-guide-photo-camera]').click()
            modal=page.locator('#guidePhotoCamera');expect(modal).to_be_visible()
            expect(modal.locator('[data-take-photo]')).to_be_enabled()
            modal.locator('[data-take-photo]').click()
            expect(modal).to_have_count(0)
            expect(page.locator('.delivery-evidence .delivery-photo-preview')).to_be_visible()
            self.assertTrue(page.evaluate('qaPhotoStream.getTracks().every(t=>t.readyState==="ended")'))
            self.assertEqual(posts,[])
            page.locator('#deliveryRecipientSigned').check();page.locator('#deliveryWarehouseSigned').check()
            with page.expect_response(lambda r:r.url.endswith('/delivery-evidence') and r.request.method=='POST') as response:
                page.locator('#uploadDeliveryEvidence').click()
            self.assertEqual(response.value.status,200)
            with app.db() as db:
                self.assertIsNotNone(app.attention_payload(db,self.ui.documents['OV'][2])['delivery_evidence'])
            self.assertEqual(errors,[])

    def test_denied_camera_keeps_file_alternative_and_cancel_releases_camera(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            page,errors,posts=self.ui.page('OV','picker')
            page.set_default_timeout(4000)
            page.evaluate("() => {navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('denied','NotAllowedError')}}")
            page.locator('[data-guide-photo-camera]').click()
            expect(page.locator('#guidePhotoCamera [role=alert]')).to_contain_text('permiso')
            page.locator('#guidePhotoCamera [data-close-photo]').click()
            expect(page.locator('#deliveryEvidenceFile')).to_be_visible()
            from base64 import b64decode
            from tests.test_dispatch_sts import PHOTO
            page.locator('#deliveryEvidenceFile').set_input_files({'name':'guia-qa.png','mimeType':'image/png','buffer':b64decode(PHOTO['image_base64'])})
            expect(page.locator('.delivery-evidence .delivery-photo-preview')).to_be_visible()
            self.camera(page);page.locator('[data-guide-photo-camera]').click()
            expect(page.locator('#guidePhotoCamera [data-take-photo]')).to_be_enabled()
            page.locator('#guidePhotoCamera [data-close-photo]').click()
            self.assertTrue(page.evaluate('qaPhotoStream.getTracks().every(t=>t.readyState==="ended")'))
            self.assertEqual(page.locator('#deliveryEvidenceFile').evaluate('(input)=>input.files[0].name'),'guia-qa.png')
            self.assertEqual(posts,[]);self.assertEqual(errors,[])

    def test_closing_while_permission_is_pending_stops_late_camera_stream(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            page,errors,posts=self.ui.page('OV','picker')
            page.evaluate('''()=>{navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>window.qaResolve=resolve)}''')
            page.locator('[data-guide-photo-camera]').click()
            expect(page.locator('#guidePhotoCamera')).to_be_visible()
            page.locator('#guidePhotoCamera [data-close-photo]').click()
            page.evaluate('''()=>{const c=document.createElement('canvas');c.width=32;c.height=32;
                window.qaLateStream=c.captureStream(1);qaResolve(qaLateStream);}''')
            page.wait_for_function('qaLateStream.getTracks().every(t=>t.readyState==="ended")')
            expect(page.locator('#guidePhotoCamera')).to_have_count(0)
            self.assertEqual(posts,[]);self.assertEqual(errors,[])

    def test_changing_attention_closes_photo_without_saving(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            page,errors,posts=self.ui.page('OV','picker');self.camera(page)
            page.locator('[data-guide-photo-camera]').click()
            expect(page.locator('#guidePhotoCamera [data-take-photo]')).to_be_enabled()
            page.once('dialog',lambda d:d.accept())
            page.evaluate('(code)=>loadDetail(code)',self.ui.documents['STS'][0])
            expect(page.locator('#guidePhotoCamera')).to_have_count(0)
            self.assertTrue(page.evaluate('qaPhotoStream.getTracks().every(t=>t.readyState==="ended")'))
            self.assertEqual(posts,[]);self.assertEqual(errors,[])

    def test_sts_receipt_dialog_reuses_camera_and_signature_checks(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            page,errors,posts=self.ui.page('STS','demo.admin');self.camera(page)
            page.locator('[data-receive]').click()
            receipt=page.locator('dialog').filter(has=page.locator('[name=receiver]'))
            receipt.locator('[name=receiver]').fill('Receptor QA')
            receipt.locator('[data-guide-photo-camera]').click()
            expect(page.locator('#guidePhotoCamera [data-take-photo]')).to_be_enabled()
            page.locator('#guidePhotoCamera [data-take-photo]').click()
            expect(receipt.locator('.delivery-photo-preview')).to_be_visible()
            receipt.locator('[name=recipient]').check();receipt.locator('[name=warehouse]').check()
            with page.expect_response(lambda r:r.url.endswith('/receive') and r.request.method=='POST') as response:
                receipt.locator('[type=submit]').click()
            self.assertEqual(response.value.status,200);self.assertEqual(errors,[])

    def test_photo_dialog_fits_phone_and_landscape(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            for width,height in ((320,640),(873,393)):
                page,errors,posts=self.ui.page('OV','picker',width,height);self.camera(page)
                page.locator('[data-guide-photo-camera]').click()
                expect(page.locator('#guidePhotoCamera [data-take-photo]')).to_be_enabled()
                self.assertLessEqual(page.locator('#guidePhotoCamera').bounding_box()['width'],width)
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                page.locator('#guidePhotoCamera [data-close-photo]').click()
                self.assertEqual(posts,[]);self.assertEqual(errors,[]);page.context.close()


if __name__=='__main__':unittest.main()
