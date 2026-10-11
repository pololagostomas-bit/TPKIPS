# Reception Work Overlay

Apply this only after the pull request has been reviewed and merged, separately
to each approved barcode/manual base. It preserves variant-specific scanners,
truck workflows, authentication, Microsoft connection, data and startup command.

The overlay installs the read-only work projection, its two assets and bounded
GET endpoint. The full-IP accounting option defaults to the existing behavior;
only the work projection requests all expected IPs. Guards abort the build when
a base has an unknown or partial integration. No database migration is needed.

Before rollout, run the reception work tests and disposable HTTP/browser checks
on both candidate images, without production volumes or network access. Take
the normal variant-specific backup, then use the approved deployment process.
Do not replace the manual app with the barcode app or close documentary-only
BLs automatically. Production deployment is not part of preparing this overlay.
