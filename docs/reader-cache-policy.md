# Reader Client: Cache and Connection Policy

Scope: barcode-reader deployment only. No changes to the manual deployment,
business state machines, permissions, Microsoft sessions or production data.

## Operational Screens

The service worker is network-only. It does not save HTML, API data or assets
in Cache Storage. Its activation removes only legacy `triton-wms-*` and
`triton-picking-*` caches. Cookies, local/session storage, pending scanner work
and unrelated caches are not cleared.

Dispatch, reception and inventory stay behind a loading gate until the current
interface has initialized. Missing core assets show a retry state instead of
exposing the old base interface. Obsolete inline workspace fallbacks are removed.

## Server Outage

An already installed current service worker replaces failed navigation and
HTTP 5xx pages with a self-contained `Servidor no disponible` screen. This
applies to dispatch, reception, inventory, login, password change, cloud
connection and purchase alerts. It includes no operational records or forms.
Reintentar requests the current page from the server again.

A failed API request on an already open page shows a connection warning.
Retry checks `/health`; success hides the warning without reloading the page
or submitting its forms. Mutations are never automatically replayed. Aborted
queries remain aborted and do not announce a connection failure. Auth 401/403
responses retain their normal behavior.

## Rollout and Limits

Merge and deploy this change to the reader server through the approved release
process. Existing browsers must visit it online once to install the updated
worker and remove its legacy cache. A worker cannot update while the server is
unreachable. Different public tunnel URLs are different browser origins, so
old bookmarked origins cannot be updated by visiting a new URL.

New browsers without a previously installed worker show the browser's network
error during a complete outage. Unsupported/embedded browsers retain the online
client. No local offline editing or background synchronization is implemented.
Server health is checked after failed requests and reconnection events, not by
continuous polling. The server must remain available for work to be saved.

## Regression Checks

- `python -m unittest discover -s tests`
- `node tests/reader_pwa_dom.cjs` and `node tests/reader_ui_dom.cjs`
- Start disposable `tests/support_mobile_server.py PORT`, then run
  `node tests/reader_pwa_browser.cjs http://127.0.0.1:PORT`.
- The browser regression reproduces the old cached UI, installs the replacement,
  shuts down its disposable proxy and checks all seven routes, narrow/landscape
  layouts, asset failures, loading and unsaved-form recovery.
- Use a separate fresh fixture for `tests/reader_ui_browser.cjs`; its scanning
  workflow modifies only synthetic QA rows. No production origin is permitted.
