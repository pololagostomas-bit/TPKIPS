"""Read-only PDF QA: physical stock, page count and independent 203dpi decode.

Run after em_labels_browser.cjs. Requires Poppler, pypdf, Pillow and zxing-cpp
in the local QA environment, not the application image.
"""
import subprocess
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
import zxingcpp


def verify(folder):
    raster = folder / 'raster'
    raster.mkdir(exist_ok=True)
    catalog = ['KALMAR','TRITON','CROWN','HYUNDAI','BOBCAT','KUBOTA',
               'HOWO','TVH','HUSQVARNA','LIEBHERR']
    for name, dimensions, expected in (
        ('landscape', (288,216), ['NP-001','NP-001','NP-NOSTOCK']),
        ('portrait', (216,288), ['NP-001','NP-001','NP-NOSTOCK']),
        ('all-brands', (288,216), ['QA-' + brand for brand in catalog]),
    ):
        document = folder / (name + '.pdf')
        reader = PdfReader(document)
        assert len(reader.pages) == len(expected), (name, 'unexpected page count')
        for page in reader.pages:
            assert abs(float(page.mediabox.width) - dimensions[0]) < .6, (name, 'wrong width')
            assert abs(float(page.mediabox.height) - dimensions[1]) < .6, (name, 'wrong height')
        if name != 'all-brands':
            expected_customer = 'Cliente dos de operaciones industriales y servicios de mantenimiento ' * 2
            text = ''.join(reader.pages[1].extract_text().split())
            assert ''.join(expected_customer.split()) in text, (name,'customer text clipped')
        subprocess.run(['pdftoppm','-r','203','-gray','-png',str(document),str(raster / name)],
                       check=True,capture_output=True,timeout=60)
        for index, code in enumerate(expected, 1):
            image = raster / (name + '-' + str(index).zfill(len(str(len(expected)))) + '.png')
            with Image.open(image) as bitmap:
                barcodes = zxingcpp.read_barcodes(bitmap, formats=zxingcpp.BarcodeFormat.DataMatrix)
            assert [barcode.text for barcode in barcodes] == [code], (name,index,'barcode mismatch')
        print(f'OK: {name}, {len(expected)} pages, {dimensions} pt, all Data Matrix NPs decoded at 203dpi')


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    verify(root / 'qa' / 'em-labels')
    layout = root / 'qa' / 'em-labels-layout'
    if (layout / 'reference.pdf').exists():
        reader = PdfReader(layout / 'reference.pdf')
        assert len(reader.pages) == 3
        prefix = layout / 'reference'
        subprocess.run(['pdftoppm','-r','203','-gray','-png',str(layout / 'reference.pdf'),str(prefix)],
                       check=True,capture_output=True,timeout=60)
        for index, code in enumerate(['QA31-02110','QA31-02110','QA-125070-401'],1):
            page = reader.pages[index-1]
            assert abs(float(page.mediabox.width)-288)<.6 and abs(float(page.mediabox.height)-216)<.6
            for field in [code, 'QA-BL-001', 'Cliente', 'Ubicación']:
                assert field.casefold() in page.extract_text().casefold(), (index,'missing label field',field)
            with Image.open(layout / f'reference-{index}.png') as bitmap:
                assert [item.text for item in zxingcpp.read_barcodes(bitmap,formats=zxingcpp.BarcodeFormat.DataMatrix)] == [code]
        print('OK: reference layout, 3 pages, all agreed fields, 4x3in, Data Matrix decoded at 203dpi')
