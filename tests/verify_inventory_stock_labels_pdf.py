"""Independent physical-page and Data Matrix checks for synthetic label output."""
import json
import sys
from pathlib import Path

import pymupdf as fitz
from PIL import Image
import zxingcpp

source = Path(sys.argv[1])
expected = ['ICM/2022-273.a', 'NP-NOSTOCK']
with fitz.open(source) as document:
    assert len(document) == len(expected)
    for page, code in zip(document, expected):
        assert abs(page.rect.width - 288) < 0.6
        assert abs(page.rect.height - 216) < 0.6
        text = page.get_text()
        assert code in text
        assert all(value not in text for value in ('# OV', 'BL / AWB', 'Cliente', 'Cantidad', 'PRIVATE-'))
        raster = page.get_pixmap(matrix=fitz.Matrix(203 / 72, 203 / 72), colorspace=fitz.csGRAY)
        image = Image.frombytes('L', (raster.width, raster.height), raster.samples)
        decoded = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.DataMatrix)
        assert [barcode.text for barcode in decoded] == [code]
        assert 'STALE-LOCATION' not in text
print(json.dumps({'pages': len(expected), 'size_mm': [101.6, 76.2], 'decoded_dpi': 203, 'status': 'PASS'}))
