"""Read-only QA of 2-up location labels at the printer's 203 dpi target."""
import subprocess
from pathlib import Path

from PIL import Image, ImageChops
from pypdf import PdfReader
import zxingcpp

folder = Path(__file__).resolve().parents[1] / 'qa' / 'location-capacity'
raster = folder / 'raster'
raster.mkdir(exist_ok=True)
jobs = {'odd-three': [['01-01-A-01-01','01-02-A-01-01'],['01-03-A-01-01',None]],
        'two-copies': [['01-01-A-01-01','01-01-A-01-01']]}
for name, expected in jobs.items():
    source = folder / (name + '.pdf')
    document = PdfReader(source)
    assert len(document.pages) == len(expected)
    subprocess.run(['pdftoppm','-r','203','-png',str(source),str(raster / name)],
                   check=True,capture_output=True,timeout=60)
    for index, codes in enumerate(expected, 1):
        page = document.pages[index-1]
        assert abs(float(page.mediabox.width)-288) < .6 and abs(float(page.mediabox.height)-216) < .6
        assert 'TSC TE200' not in page.extract_text(), 'Print toolbar must not appear on paper'
        with Image.open(raster / f'{name}-{index}.png') as bitmap:
            red, green, blue = bitmap.convert('RGB').split()
            assert ImageChops.difference(red,green).getextrema()[1] <= 2
            assert ImageChops.difference(green,blue).getextrema()[1] <= 2
            for half, code in enumerate(codes):
                start, end = half * bitmap.height // 2, (half + 1) * bitmap.height // 2
                area = bitmap.crop((0,start,bitmap.width,end))
                values = zxingcpp.read_barcodes(area, formats=zxingcpp.BarcodeFormat.DataMatrix)
                assert [value.text for value in values] == ([code] if code else []), (name,index,half)
                if code:
                    assert code in page.extract_text()
                    logo = bitmap.crop((45,start+40,560,start+180)).convert('L')
                    ratio = sum(logo.histogram()[:80]) / (logo.width * logo.height)
                    assert .02 < ratio < .5, 'Logo ink missing or white background turned black'
    print(f'OK: {name}, {len(expected)} physical 4x3 pages, 2 halves/page, exact Data Matrix locations at 203 dpi, monochrome logo')
