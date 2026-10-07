# Truck Controls

Both variants use truck-controls.js and truck-controls.css. The manual variant remains an independent local distribution; this repository serves the scanner variant.

- List navigation and discarding unsaved fields do not reverse persisted receipts.
- During scanner arrival, Back returns to BL selection and keeps saved package scans.
- Manual arrival before saving can return to the local transit screen.
- After location completion, administrative Back reopens location and preserves quantities and locations.
- From location, administrative Back annuls only this truck arrival to allow quantities/packages to be registered again. Confirmation explains the effect. Existing BL counting guards still apply.
- Cancelling the reception is confirmed, audited and atomic. Assistants can cancel before arrival is stored; administrators can cancel stored arrivals unless BL counting prevents reversal.
- Cancelled guides stay inactive after schema initialization; documents and other truck arrivals remain intact.
- Scanner header, controls and stage action remain outside the scrolling form. BL history cannot resize the screen; feedback does not cover actions.

Verification: unit tests in test_truck_controls.py; disposable browser fixture support_truck_controls_server.py and truck_controls_browser.cjs at 1366x900, 375x812 and 320x640. These simulate typed/HID input, not physical reader hardware or camera recognition.
