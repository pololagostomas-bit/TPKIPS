"""WSGI transport for the existing routes, served by Waitress on Windows/Linux.

The adapter invokes route methods directly. It never opens an http.server socket.
"""
import io
import logging
import os
import threading
from email.message import Message
from http import HTTPStatus
from urllib.parse import quote

from backend import app


class Request(app.Handler):
    def __init__(self, environ):
        self.path = quote(environ.get('PATH_INFO','/'), safe='/@:+')
        if environ.get('QUERY_STRING'):
            self.path += '?' + environ['QUERY_STRING']
        self.command = environ.get('REQUEST_METHOD','GET')
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith('HTTP_'):
                self.headers[key[5:].replace('_','-')] = str(value)
        for key in ('CONTENT_LENGTH','CONTENT_TYPE'):
            if environ.get(key):
                self.headers[key.replace('_','-')] = environ[key]
        self.rfile = environ['wsgi.input']
        self.wfile = io.BytesIO()
        self.client_address = (environ.get('REMOTE_ADDR',''),0)
        self.response_status = 200
        self.response_headers = []

    def send_response(self, code, message=None):
        self.response_status = code

    def send_header(self, keyword, value):
        self.response_headers.append((keyword,str(value)))

    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')


def application(environ, start_response):
    request = Request(environ)
    try:
        if request.command in {'GET','HEAD'}:
            request.do_GET()
        elif request.command == 'POST':
            request.do_POST()
        else:
            request.send_json({'error':'Método no permitido'},405)
    except Exception:
        logging.exception('Fallo de solicitud %s %s',request.command,environ.get('PATH_INFO'))
        request.wfile = io.BytesIO()
        request.response_headers = []
        request.send_json({'error':'No se pudo completar la solicitud. Vuelve a intentarlo.'},500)
    body = request.wfile.getvalue()
    headers = [(key,value) for key,value in request.response_headers if key.lower()!='content-length']
    headers.append(('Content-Length',str(len(body))))
    start_response(f'{request.response_status} {HTTPStatus(request.response_status).phrase}', headers)
    return [b'' if request.command=='HEAD' else body]


def prepare():
    os.environ.setdefault('TRITON_AUTH_MODE','local')
    app.init_db()
    if os.environ['TRITON_AUTH_MODE'] == 'local':
        with app.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            app.identity.bootstrap_admin(connection,app.ROLES)
    with app.db() as connection:
        app.seed_initial_attentions(connection)


def serve(host=None, port=None):
    from waitress import serve as waitress_serve
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    stop = threading.Event()
    if os.getenv('TRITON_MAIL_ENABLED','0') == '1':
        from backend.services.notifications import process_notifications
        def mail_loop():
            while not stop.is_set():
                try:
                    outcome = process_notifications(app.DB_PATH)
                    if outcome['config_error']:
                        logging.warning('Correo pendiente de configuración: %s',outcome['config_error'])
                except Exception:
                    logging.exception('No se pudo procesar la bandeja de correos')
                stop.wait(60)
        threading.Thread(target=mail_loop,daemon=True,name='wms-mail').start()
    try:
        waitress_serve(application,host=host or os.getenv('HOST','127.0.0.1'),
                       port=port or int(os.getenv('PORT','8000')),threads=6,
                       max_request_body_size=app.MAX_IMPORT_BYTES,channel_timeout=60)
    finally:
        stop.set()


if __name__ == '__main__':
    prepare()
    serve()
