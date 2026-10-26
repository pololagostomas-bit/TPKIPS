"""The real WSGI adapter must not re-buffer complete report files."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend import wsgi


class ReportStreamTests(unittest.TestCase):
    def request(self,method='GET'):
        return wsgi.Request({'PATH_INFO':'/qa-file','REQUEST_METHOD':method,'wsgi.input':io.BytesIO()})

    def serve_file(self,request,path):
        request.send_header('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        request.send_header('Content-Length',str(path.stat().st_size))
        request.send_report_file(path)

    def test_wsgi_file_response_keeps_web_buffer_empty_and_reads_bounded_chunks(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'qa.xlsx';path.write_bytes(b'Q'*(1024*1024))
            request=self.request()
            self.assertTrue(hasattr(request,'send_report_file'))
            with patch.object(wsgi,'Request',return_value=request),patch.object(request,'do_GET',side_effect=lambda:self.serve_file(request,path)):
                headers=[]
                body=wsgi.application({},lambda status,values:headers.extend(values))
                self.assertEqual(request.wfile.tell(),0)
                sizes=[len(chunk) for chunk in body]
            self.assertEqual(sum(sizes),1024*1024)
            self.assertLessEqual(max(sizes),65536)
            self.assertIn(('Content-Length',str(1024*1024)),headers)
            self.assertTrue(request.file_response.closed)

    def test_head_and_early_close_close_the_file_without_reading_it(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'qa.xlsx';path.write_bytes(b'QA')
            for method in ('GET','HEAD'):
                request=self.request(method)
                self.assertTrue(hasattr(request,'send_report_file'))
                with patch.object(wsgi,'Request',return_value=request),patch.object(request,'do_GET',side_effect=lambda:self.serve_file(request,path)):
                    body=wsgi.application({},lambda *args:None)
                    if method=='HEAD':self.assertEqual(body,[b''])
                    else:body.close()
                self.assertTrue(request.file_response.closed)

    def test_start_response_failure_closes_the_report_file(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'qa.xlsx';path.write_bytes(b'QA')
            request=self.request()
            self.assertTrue(hasattr(request,'send_report_file'))
            with patch.object(wsgi,'Request',return_value=request),patch.object(request,'do_GET',side_effect=lambda:self.serve_file(request,path)):
                with self.assertRaises(RuntimeError):wsgi.application({},lambda *args:(_ for _ in ()).throw(RuntimeError('QA disconnected')))
            self.assertTrue(request.file_response.closed)
