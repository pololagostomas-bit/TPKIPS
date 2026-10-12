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
- Explicit `help-guidance` markup marks tutorials and optional explanations.
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
