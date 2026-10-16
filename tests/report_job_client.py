"""Follow the asynchronous read contract against an isolated test server."""
import json
import time
from urllib.request import Request, urlopen


def wait_response(request, timeout=30):
    response = urlopen(request, timeout=5)
    if response.status != 202:
        return response
    job = json.load(response)
    response.close()
    from urllib.parse import urlsplit
    parts = urlsplit(request.full_url)
    base = parts.scheme + '://' + parts.netloc
    headers = dict(request.header_items())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with urlopen(Request(base + job['status_url'], headers=headers), timeout=5) as status:
            state = json.load(status)
        if state['status'] == 'READY':
            return urlopen(Request(base + job['result_url'], headers=headers), timeout=5)
        time.sleep(.05)
    raise AssertionError('The disposable report worker did not finish')
