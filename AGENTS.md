# Triton WMS Frontend

For UI creation, changes or reviews, read
`.agents/skills/wms-frontend-standards/SKILL.md`, then
`design-system/triton-wms/MASTER.md`. Load only the relevant linked references.
Use `ui-ux-pro-max` for targeted guidance when available; its generated suggestions
do not replace the WMS contract. Do not regenerate a different visual identity for
each request. If a request explicitly changes a convention, update its source.

Keep Python and the existing HTML/CSS/JavaScript architecture unless a migration
is explicitly in scope. Reuse the current API, shell, permission checks and state
machines. The maintained UI is the barcode-reader version; the separate manual
deployment is frozen unless explicitly requested.

Before changing a screen, identify its role, entity, task, primary action and
mobile/desktop behavior. Verify the changed workflow with disposable data and
report exactly what was tested. A desktop viewport is not a physical Android test.

Use the established PR approval workflow. Publishing a PR does not authorize
merging, deployment, service restarts, production data changes or real emails.
Keep operational records, workbooks, logos, tokens and private configuration out
of this public repository. Check current status instead of assuming an old note
proves a service or pull request is still in that state.
