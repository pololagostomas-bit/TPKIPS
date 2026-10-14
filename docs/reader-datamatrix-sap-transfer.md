# Reader: Data Matrix and SAP transfer confirmation

Only the barcode reader variant is changed. Review and merge the PR before
installing its image; do not overlay these changes into the frozen manual app.

## Labels

- Plain ECC200 Data Matrix encodes the exact NP/SKU, including punctuation and
  case. It contains no BL, OV, destination, URL, GS1 identifier or inventory action.
- The pinned MIT bwip-js browser bundle is loaded locally only when printing,
  not on each reception screen load. No remote barcode service receives SKUs.
- 4 x 3 inch TSC TE200 landscape remains the default. NP and OV share type size;
  manufacturer logo is first, with a small separate Triton logo. Original logo
  files remain private in the existing server volume, not in this repository.
- The square symbol has a white quiet zone of at least one module on each side.
  Oversized symbols fail closed instead of producing unreadably dense labels.
- Print is available beside Save complete review in Inicio de conteo, and still
  in EM. Only saved positive quantities in the selected attention are printed.
  Unsaved edits and unconfirmed initial quantity defaults must be saved first.
- No-stock locations retain the blank handwriting box. The code does not write
  stock, override the count location, or merge separate OV/source line identities.
- A 2D imaging scanner is required, or the phone camera. Existing linear NP
  labels remain searchable. The plain Data Matrix AIM prefix `]d1` is stripped
  from scanner input only; no extra DHL or GS1 prefix is invented.

The revised label follows the supplied industrial reference: centered manufacturer
header, small separate Triton mark, ruled NP/OV fields of equal large type,
full-width captioned description, BL/customer beside the protected Data Matrix,
and a full-width destination box at the bottom. Thin black rules and white
caption bands preserve monochrome printing without background ink blocks.
No agreed field is removed or abbreviated to force a fit. The existing fit guard
also checks nested text; excessive content disables printing rather than clipping.
`tests/label_layout_browser.cjs` verifies the layout and produces private,
fictitious Hyundai samples. The reference and private logos are never committed.

## Business meaning

Completing VALIDACION with CONFORME creates one new durable request for that
BL/attention. It does not scan historical BLs, send mail synchronously during
the page request, or enable the old global notification queue.

The guest check means **the IMP to 01 transfer was already performed in SAP**.
It does not mean "request reviewed", and the app does not execute SAP transfers.
Confirmation is per attention, cannot satisfy another arrival, and does not
automatically close the BL. Normal authorized closure remains a separate step.
An administrator can correct confirmation with an explicit reason and audit.

## Deployment and Private Configuration

The automatic worker starts with the reader server and checks every 60 seconds.
`WMS_TRANSFER_WORKER=0` disables it for QA. Mail is off by default in the database.
In any BL's Transferencia panel, administrators can open Configuracion del aviso:

1. Set the Microsoft sender and the intended recipient privately.
2. Set the current approved public HTTPS origin, without a path or query.
3. Authorize Mail.Send for that same sender in the existing Microsoft mail flow.
4. Enable the automatic notice. Microsoft tokens stay in the existing private
   server cache and renew silently while the authorization remains valid.

Never derive the emailed URL from Host or X-Forwarded-Host. A quick tunnel URL
is not permanent: after a tunnel change, update the configured origin and
explicitly reissue affected pending links. A token can remain unexpired while
its old tunnel is unavailable. There is no promise of a permanent free URL.
Existing accepted/error/uncertain requests are never resent just by changing
settings. Reissue invalidates the old link and records the administrator reason.

The recipient and sender are deployment data, not hard-coded into public code.
No mail should be sent from development tests; use the mocked worker tests.
Legacy notifications already present in production are not modified or flushed.

## Restricted Link

- One BL/attention, 24 hours, random 256-bit capability; only SHA-256 is stored.
- Token is in the URL fragment, removed from browser history on entry and sent
  in same-origin POST bodies, never in a server URL, audit reason or queued body.
- Public page loads no WMS session, private brand assets, external analytics,
  navigation, or broad BL list. Only BL, attention and EM summary are shown.
- Opening the email or a GET by a mail security scanner cannot confirm SAP work.
  The checkbox and confirmation POST are required. A forwarded link can be used
  by its holder: this is scoped delegated authority, not verified personal identity.
- No-store/no-referrer/CSP, strict JSON and body size, same-site/custom header,
  and persisted per-remote rate limits protect the guest endpoints. No permissive CORS.
- Reissue and administrative rewind revoke old tokens. Closed/cancelled or
  different-stage attentions reject unused tokens. Concurrent confirmation is
  transactional and idempotent; consumed tokens reveal no further BL details.

## Mail States

PENDING/BLOCKED are retryable before sending. Missing Mail.Send retries silent
authorization after five minutes. The fresh link is generated only for a claimed
send. Microsoft HTTP 202 means accepted, **not proof of delivery**. Definite HTTP
failures require operator review/reissue; timeout or a crash during sending is
REVIEW, never an automatic duplicate send. Check sent items before reissuing.
If the uncertain mail actually arrived, its still-valid link can confirm the
same scoped attention normally, without requiring another email.
The Transferencia panel displays the state and exposes administrator-only settings
and reissue; operators can refresh the SAP confirmation without closing early.

## Verification

`test_reception_transfer.py` covers local-auth routing, scope, strict confirmation,
expiry, revocation, independent arrivals, concurrency, configuration, CSRF/rate
limits, mocked silent Microsoft authorization and ambiguous sends. Browser tests
cover five desktop/mobile viewports and link reuse/expiry without WMS access.
Label PDFs are independently decoded as Data Matrix at 203 dpi. Physical TE200
printing and the actual company 2D scanner remain acceptance tests after merge.

References: [bwip-js](https://github.com/metafloor/bwip-js),
[GS1 symbol guidance](https://www.gs1.org/standards/gs1-datamatrix-guideline/25),
[OWASP capability token principles](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).
The token principles are applied to this limited confirmation flow, not a claim
that it implements password recovery or GS1-certified inventory identification.
