# Reader Display Preferences

Scope: the barcode-reader application only. The separate manual application
and production data are not changed. This follows PR15 on approved `main`;
another PR approval and merge are required before a production build.

## Display Contract

- Informational help is hidden by default. The authenticated user's existing
  `show_guidance` preference is stored by `/api/account/preferences` and read
  from `/api/account`; it is not a browser-wide localStorage setting.
- Mi perfil / Preferencias de ayuda controls this option. Labels and the save
  result stay visible even when help is hidden.
- Explicit `help-guidance` markup marks tutorials and optional explanations,
  plus complementary technical references in operational tables.
  Text matching and hiding all `section-note` elements are no longer used.
- Errors, warnings, confirmations, operational states, required fields,
  administrative commands, business observations and audit history remain
  available. Complementary business records remain in their existing
  on-demand sections; they are not deleted or treated as tutorials.
- Inventory and independent cloud/purchase pages load the same preference
  once. Workspace screens reuse their existing profile request; this does not
  add polling, a cache of operational records or duplicate account requests.
- Failure to read a preference leaves optional help hidden. It does not hide
  connection, authorization or form errors.

## Concise NP Work

Mi perfil labels the existing option `Mostrar ayudas y detalles adicionales`.
It controls source line IDs and supplementary OV/IP/SAP-reference/stock columns
in count and location, and optional OV/help in EM. FR/EM identifiers and their
IP association, required actions, admin controls, errors and printed OV labels
remain available; this presentation change never changes row ownership or data.

A normal scan shows NP, description, requirement and a zero-stock status only.
OV/IP/line IDs are optional, never in save toasts. Ambiguous NPs keep an explicit
order choice: opening a candidate reveals business references before selection.
No automatic first-match selection or consolidation. Quantity is prefilled from
the integer count/draft, normally the full planned quantity, preserving saved
differences and zeroes; the operator still confirms Save. The location field is
named `Ubicacion por defecto`, while keeping its existing attention-specific
snapshot, blank/no-stock behavior and stage permissions.

`reception_np_concise_browser.cjs` covers these rules and the saved preference
on desktop and four mobile/landscape sizes. This uses only the disposable items
fixture, never operational records. The existing all-module guidance suite still
checks96 views with errors, feedback and administrative actions visible.

## Operational Cleanup

Transit shows truck counts and the existing truck list/actions, not a prompt
to select a BL. No extra truck-registration command or receiving shortcut is
created. Profile credits do not follow the user into every operational view.
Personal review markers, MVP labels and obsolete deployment instructions are
removed. FR prerequisites remain warnings even with help turned off.

## Verification

`tests/reader_guidance_browser.cjs` uses the disposable all-module fixture,
saves preferences, tests persistence and checks explicit help plus critical
feedback across five screen sizes. Python session tests verify per-user
isolation, authentication, CSRF and boolean validation. Shared UI and scanner
regressions remain applicable. Browser fixtures contain synthetic records and
are not a certification of Android camera/HID hardware or corporate mail.

Verified on 2026-10-12: 444 Python tests (442 passing, two expected manual-only
skips), 96 preference views, 165 shared responsive views with scanner recovery
and return, and three performance viewports. Enlarged-text checks confirm
navigation-label containment, header separation and workspace clearance.
Cloud/purchase services are mocked, including their unavailable state. JS
response/cache boundaries, syntax and `git diff --check` also pass.
