# html5-qrcode 2.3.8

The reader previously downloaded this same version from a third-party CDN on
each first camera use. The unmodified browser bundle is now served locally and
loaded only when the operator opens the camera. No framework or scanner engine
was replaced. QR, Data Matrix and linear codes remain decoded by the upstream
library, not by application-specific image processing.

- Upstream: https://github.com/mebjas/html5-qrcode
- Package: https://registry.npmjs.org/html5-qrcode/2.3.8
- Tarball: https://registry.npmjs.org/html5-qrcode/-/html5-qrcode-2.3.8.tgz
- License: Apache-2.0; upstream LICENSE accompanies this file.
- Tarball SHA512 (npm integrity, verified before extraction):
  `jsr4vafJhwoLVEDW3n1KvPnCCXWaQfRng0/EEYk1vNcQGcG/htAdhJX0be8YyqMoSz7+hZvOZSTAepsabiuhiQ==`
- Bundle SHA256:
  `660b12437b1d747e3e68b8be0685c08cb728140110ad213f167b14b66f8b1d8e`

Preserve the license and upstream bundled notices when updating. Camera hardware
and browser support still require device testing; this bundle does not grant
camera permissions or make unreadable physical labels recoverable.
