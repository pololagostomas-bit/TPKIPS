"""Read-only: physical label size, generic fields and independent 203 dpi decode."""
import subprocess
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
import zxingcpp

folder = Path(__file__).resolve().parents[1] / 'qa' / 'inventory-labels'
raster = folder / 'raster'
raster.mkdir(exist_ok=True)
expected = ['ICM/2022-273.a', '31EE-02110', 'NP-NOSTOCK', 'NP-LONG']
for orientation, dimensions in [('landscape', (288, 216)), ('portrait', (216, 288))]:
    source = folder / (orientation + '.pdf')
    pages = PdfReader(source).pages
    assert len(pages) == 4, (orientation, 'unexpected page count')
    subprocess.run(['pdftoppm', '-r', '203', '-gray', '-png', str(source), str(raster / orientation)],
                   check=True, capture_output=True, timeout=60)
    for index, (page, code) in enumerate(zip(pages, expected), 1):
        assert abs(float(page.mediabox.width) - dimensions[0]) < .6
        assert abs(float(page.mediabox.height) - dimensions[1]) < .6
        text = page.extract_text()
        assert code in text and 'ubicación por defecto' in text.casefold()
        assert all(value.casefold() not in text.casefold() for value in ('# OV', 'Cliente', 'BL / AWB', 'PRIVATE-', 'STALE-LOCATION'))
        if code == 'NP-LONG':
            assert ''.join(('Repuesto industrial de prueba con descripcion extensa ' * 4).split()) in ''.join(text.split())
        with Image.open(raster / f'{orientation}-{index}.png') as bitmap:
            decoded = zxingcpp.read_barcodes(bitmap, formats=zxingcpp.BarcodeFormat.DataMatrix)
        assert [value.text for value in decoded] == [code], (orientation, index, 'wrong Data Matrix payload')
    print(f'OK: {orientation}, 4 pages, {dimensions} pt, exact Data Matrix SKU decoded at 203 dpi')
