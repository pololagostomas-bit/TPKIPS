# Reader UI review

Reviewed on 2026-10-11. Scope: the barcode reader application only. The
separate manual application and its database are not updated by this change.

## Design basis

The existing Python backend and HTML/CSS/JavaScript client are retained.
An operational WMS needs compact information, readable fields, clear actions
and permission-checked corrections. No framework migration, external font,
UI package, subscription or runtime CDN was added.

The locally installed [UI UX Pro Max skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
was inspected at revision `67803eac81607188194aea9842a723b89326d90d`.
Its MIT license and local search scripts were checked. Applicable guidance
covered touch controls, visible keyboard focus, non-obscured modal fields,
validation feedback and reduced motion. Marketing-page recommendations were
not applied to operational screens. The skill itself is not vendored here.

## Review and changes

- Reception, BL stages, truck workflow, dispatch, inventory, account, users,
  picking reports, notifications, daily Excel cuts, cloud connection, purchase
  alerts and login share scoped reader styles. Mobile fields use 16px text,
  buttons have a minimum 44px height, and long values wrap.
- New BL, reporting and user dialogs isolate background controls, contain
  keyboard focus, support Escape through the existing close action and restore
  the opener. Their scrolling height follows the visible viewport. Modal
  layering no longer lets the side rail cover form fields.
- Delayed users, workload or notification responses cannot overwrite a newer
  screen. Administrative state controls, confirmations, reasons, backend role
  checks and auditing remain in place.
- Plain-text HTTP errors become readable API errors. Expired sessions redirect
  to login, unsuccessful login does not redirect in a loop, unexpected HTML
  responses are not reported as successful, and valid Excel/CSV exports are
  retained. Login errors receive focus; repeated submission is disabled.
- Failed package readings remain visible after subsequent successes. Retry
  uses the original truck, BL and code. Finishing an arrival is blocked until
  failed readings are retried or explicitly discarded. Existing duplicate
  handling remains idempotent.
- After a scanner arrival is finalized, a selected BL with no receipt, no
  package readings and zero planned packages is informational, not outstanding
  physical work for that truck. It remains in the manifest/history; no receipt,
  quantity, attention, date or BL state is manufactured. Before finalization it
  remains selectable. Real receipts still require exact locations. Non-scanner
  unknown-quantity validation is unchanged.

## Verification

Executed against disposable, synthetic data:

- Python regression suite: 412 tests, 410 passed, two existing environment or
  variant skips, no failures.
- Seven JavaScript authentication/response boundaries, including plain-text
  401/403, login, unexpected HTML and legitimate binary/CSV exports.
- Playwright/Edge: 165 captured views across 1440x900, 393x873, 375x812,
  360x780 and 873x393. Checks include page overflow, button height, modal focus,
  background isolation, side-rail occlusion and administrative visibility.
- Additional browser flow: interrupted reading, later success, retry after
  selecting another BL, duplicate reading, finalization, location, return from
  BL to its truck, late-navigation responses and rejected non-admin correction.
- Syntax checks for frontend JavaScript and `git diff --check`.

Useful commands from the repository root:

```sh
python -m unittest discover -s tests -p 'test_*.py'
node tests/reader_ui_dom.cjs
python tests/support_mobile_server.py 50645
# In another terminal, against a fresh fixture only:
node tests/reader_ui_browser.cjs http://127.0.0.1:50645
```

The browser test requires Playwright and Edge, or a browser channel selected
with `WMS_QA_BROWSER_CHANNEL`. It disables service-worker registration only
inside its disposable fixture: Playwright's generic blocking script throws in
sandboxed iframes. The application's email preview sandbox is not relaxed.
Cloud status and mail configuration are mocked; no real emails are sent.

## Boundaries

Failed readings are retained in memory during the current page session, not
in a persistent offline queue. Do not close the browser with unresolved reads.
Physical Android keyboard, camera and HID reader behavior require a real
device test. These checks do not certify Microsoft connectivity, email delivery,
offline operation or enterprise-scale performance.

Approval and merge into `main` are required before deployment. No production
restart, database migration, credentials, mail settings or manual-variant
rollout is part of this review. Existing auto-PR creation is not a test suite
and does not approve or merge changes.
