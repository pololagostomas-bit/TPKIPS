---
name: wms-frontend-standards
description: Create, change or review Triton WMS interfaces consistently across mobile and desktop, using the project's design contract and workflow checks. Not for unrelated apps or backend-only work.
---

# WMS Frontend Standards

## Start With The Existing Contract

Locate the repository root and read
[MASTER.md](../../../design-system/triton-wms/MASTER.md). It defines the WMS
interface, not a new theme for each request. Consult project memory when
available, then inspect only the current modules and tests needed. Memory is
historical evidence; current files and current user instructions resolve changes.

The client is HTML/CSS/JavaScript with a Python backend. Do not silently map it
to React, Tailwind or native Android. The manual deployment stays frozen.

## Create Or Change A Screen

Identify the role, entity, task and primary action before editing. For a new
workflow or a material interaction change, use the short
[screen contract](references/screen-contract.md); keep a small correction small.
Inspect the existing shell, API helper and nearest working component first.

Use the shared layout and semantic tokens. Keep operational facts, permissions
and state transitions in their existing owners. A layout change cannot invent
stock, receipts, completion or authorization. Separate navigation from business
reversal. Admin corrections stay discoverable, confirmed, reasoned and audited.

For `ui-ux-pro-max`, use one focused domain query for a specific UI issue. Use
its design-system mode only for genuinely new visual direction. Check the
returned product/category and reject marketing layouts for warehouse workflows.
Retry a mismatch once; if still unmatched, state the fallback and use this WMS
contract plus the official [references](references/sources.md). Do not persist
unverified recommendations or add a framework, CDN or animation to satisfy them.

Implement one responsive workflow, not duplicate mobile and desktop business
logic. Test the action and its error/retry path in both layouts. Follow the
[delivery checks](references/delivery.md), selecting tests proportional to scope.

## Finish

Report the visible changes, tested devices/viewports and remaining gaps. Keep
implementation, PR publication, approval and installation as separate states.
No service or production mutation follows from this skill alone.

Update the master only when a shared convention changes. A module-specific
exception belongs in the screen contract with its reason, affected users and
test, not as another global CSS override. Update focused project memory after a
verified lasting decision. Do not load the whole vault or all references each run.
