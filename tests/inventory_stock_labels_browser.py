"""Real Edge checks against the disposable inventory fixture, never production."""
import json
import re
import sys
import time
from io import BytesIO
from pathlib import Path
from openpyxl import Workbook
from playwright.sync_api import sync_playwright, expect

base, output = sys.argv[1:3]
assert re.fullmatch(r'http://127\.0\.0\.1:\d+', base), 'Disposable loopback server required'
out = Path(output); out.mkdir(parents=True, exist_ok=True)
results = []
with sync_playwright() as driver:
    browser = driver.chromium.launch(headless=True, channel='msedge')
    try:
        for width, height in ((1366, 900), (393, 873), (320, 640), (873, 393)):
            context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce',
                                          service_workers='block',
                                          extra_http_headers={'X-User': 'qa.picker', 'X-Role': 'PICKER'})
            context.add_init_script('window.print=()=>{window.qaPrints=(window.qaPrints||0)+1}')
            page = context.new_page(); errors = []; requests = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: requests.append(req.url))
            page.goto(base + '/inventory?tab=labels')
            expect(page.locator('#role')).to_have_value('PICKER')
            expect(page.locator('#labelsPanel')).to_be_visible()
            assert not any('bwip-js' in url for url in requests)
            page.locator('#stockLabelText').fill('NP\tCantidad\nICM/2022-273.a\t99\nNP-NOSTOCK\t2\nICM/2022-273.a\t200\nMISSING\t5')
            page.locator('#stockLabelPrepare').click()
            expect(page.locator('#stockLabelSummary')).to_contain_text('2 etiquetas listas', timeout=15000)
            expect(page.locator('#stockLabelSummary')).to_contain_text('1 filas repetidas')
            expect(page.locator('#stockLabelSummary')).to_contain_text('1 NP sin coincidencia')
            assert page.locator('#stockLabelRows tr').count() == 2
            for selector in ('#stockLabelPrepare', '#stockLabelPrint', '#stockLabelText'):
                assert page.locator(selector).bounding_box()['height'] >= 44
            if width <= 820:
                bounds = page.locator('#stockLabelPrint').bounding_box()
                assert bounds['y'] >= 60 and bounds['y'] + bounds['height'] < height - 65
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            page.screenshot(path=str(out / f'screen-{width}.png'), full_page=True)
            with page.expect_popup() as opening:
                page.locator('#stockLabelPrint').click()
            popup = opening.value
            popup.wait_for_selector('.inventory-sticker')
            expect(popup.locator('#printLabels')).to_be_enabled(timeout=15000)
            assert popup.locator('.label-page').count() == 2
            assert popup.locator('.ov,.customer,.bl,.quantity').count() == 0
            assert popup.locator('.np').all_text_contents() == ['ICM/2022-273.a', 'NP-NOSTOCK']
            assert popup.locator('.location-box').nth(1).inner_text() == ''
            assert popup.locator('#labelWidth').input_value() == '101.6'
            assert popup.locator('#labelHeight').input_value() == '76.2'
            popup.screenshot(path=str(out / f'labels-{width}.png'), full_page=True)
            if width == 1366:
                popup.pdf(path=str(out / 'stock-labels.pdf'), prefer_css_page_size=True, print_background=True)
            popup.close()
            # Transport errors retain the input and permit an explicit retry.
            page.route('**/api/inventory/labels/parse', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"Prueba sin conexión"}'))
            page.locator('#stockLabelPrepare').click()
            expect(page.locator('#stockLabelStatus')).to_contain_text('Prueba sin conexión')
            assert 'ICM/2022-273.a' in page.locator('#stockLabelText').input_value()
            expect(page.locator('#stockLabelPrepare')).to_be_enabled()
            page.unroute('**/api/inventory/labels/parse')
            held = []
            page.route('**/api/inventory/labels/parse', lambda route: held.append(route))
            page.locator('#stockLabelPrepare').click()
            expect(page.locator('#stockLabelCancel')).to_be_enabled()
            page.locator('#stockLabelCancel').click()
            expect(page.locator('#stockLabelStatus')).to_contain_text('cancelada')
            expect(page.locator('#stockLabelPrepare')).to_be_enabled()
            assert 'ICM/2022-273.a' in page.locator('#stockLabelText').input_value()
            for route in held:
                try: route.abort()
                except Exception: pass  # The browser may already have cancelled the request.
            page.unroute('**/api/inventory/labels/parse')
            page.locator('#stockLabelPrepare').click()
            expect(page.locator('#stockLabelPrint')).to_be_enabled(timeout=15000)
            if width == 1366:
                # The confirmed maximum is one job with 500 different codes.
                book = Workbook(); book.active.append(['SKU', 'Cantidad'])
                for i in range(500): book.active.append([f'QA{i:04d}', 200])
                book.active.append(['QA0000', 999])
                data = BytesIO(); book.save(data); book.close()
                page.locator('#stockLabelText').fill('')
                page.locator('#stockLabelFile').set_input_files({'name': 'stock-500.xlsx',
                    'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    'buffer': data.getvalue()})
                started = time.monotonic(); page.locator('#stockLabelPrepare').click()
                expect(page.locator('#stockLabelSummary')).to_contain_text('500 etiquetas listas', timeout=30000)
                expect(page.locator('#stockLabelSummary')).to_contain_text('1 filas repetidas')
                prepare_seconds = time.monotonic() - started
                assert page.locator('#stockLabelRows tr').count() == 50
                with page.expect_popup() as opening:
                    page.locator('#stockLabelPrint').click()
                popup = opening.value
                expect(popup.locator('#printLabels')).to_be_enabled(timeout=30000)
                assert popup.locator('.label-page').count() == 500
                assert popup.locator('.sticker[data-fits="false"]').count() == 0
                assert len(set(popup.locator('.np').all_text_contents())) == 500
                results.append({'width': width, 'labels': 500, 'prepare_seconds': round(prepare_seconds, 3)})
                popup.close()
            else:
                results.append({'width': width, 'labels': 2})
            assert not errors, errors
            context.close()
    finally:
        browser.close()
(out / 'browser-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
print(json.dumps(results, indent=2))
