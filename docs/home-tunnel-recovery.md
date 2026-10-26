# Reader Tunnel Recovery Without AI

Standalone Python/systemd on the Linux server; no Codex session, model, daily
automation, mailbox or application DB is needed. It may restart ONLY the exact
triton-wms-home-tunnel-1 container. Never restarts the app, Docker, Linux/WSL,
Windows, a manual container or a deployment. Keep installed source root-owned.

## Policy

- Timer checks60s after the previous run finishes. A check can take longer when
  network requests time out; this is not an exact60s uptime guarantee.
- First verify local /health on127.0.0.1:8086. Bad app means no tunnel restart.
- Read tunnel metadata and latest URL from timestamped logs of THIS startup,
  bounded to2000lines. If logs rotated, a saved URL is reusable only for the
  identical unrounded Docker StartedAt, and still needs fresh HTTPS checks.
- Require /health200 JSONstatusok and /login200 containing Triton WMS, with no
  redirects and bounded responses. Authentication redirects/401/403 and429 are
  separate states, never restart candidates.
- Failed public checks require working Internet, two consecutive failures,
  a120s startup grace,600s cooldown and at most3attempts per hour.
- Restart budget is written atomically BEFORE calling Docker, even if the
  command fails or its result is ambiguous. Unknown/corrupt state fails closed.
- Healthy URLs never restart the tunnel. Paused/restarting/dead/removing
  containers need attention rather than automatic deletion/unpause/recreation.
- Maintenance marker /var/lib/triton-wms-tunnel/maintenance disables recovery.

## Install And Operate

Deploy reviewed source as /usr/local/lib/triton-wms-tunnel/tunnel_guard.py and the
matching service/timer under /etc/systemd/system. Validate with systemd-analyze
verify, reload systemd, then enable --now triton-wms-tunnel-guard.timer.
Owner approval is required for installation/service changes; publishing code
does not authorize changing another server. No application deployment needed.

State lives at /var/lib/triton-wms-tunnel/status.json, directory0700/files0600.
current-link.txt contains a URL only after a successful current check; otherwise
it is empty, never a misleading old link. State includes check/verification time,
generation, consecutive failures and restart timestamps, no credentials or rows.
Consumers must also reject stale checked_at/verified_at timestamps if the timer
or host stops. A bare text URL is not proof of continued availability. Failed
Docker checks withdraw the current link without resetting restart history.
Inspect with systemctl list-timers, systemctl status and journalctl -u
triton-wms-tunnel-guard.service. Explicit systemctl start runs one check; it
does not bypass the maintenance/cooldown/budget rules. Stop/disable the timer
before maintenance or removal; do not delete a live lock or reset a budget just
to force retries. Preserve unknown state for diagnosis rather than resetting it.

The service has an OS lock, private temp, read-only system/home protections,
96MiB memory and10%CPU ceilings. Docker socket authority is still privileged:
these limits do not make an untrusted script safe. No incoming branch is run
automatically, no shell commands/remote source downloaded by this guard.

## Boundaries

Cloudflare Quick Tunnels provide temporary URLs and no uptime guarantee:
https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ . A new tunnel
may change its URL; a watchdog does not create a fixed public hostname.
Its latest validated link remains in server state. The cancelled daily mail
automation must remain cancelled; conditional URL-change mail is separate below.

A process INSIDE Linux cannot recover a sleeping/offline machine or frozen WSL
engine. It starts with Linux and resumes checks when Linux/Docker/network work.
It deliberately cannot reboot a laptop or terminate a VM automatically. Avoid
claiming complete host recovery or24/7 external availability from this timer.

On WSL, retain the existing host launcher/keepalive session as well: systemd
services alone do not keep a distribution alive. This timer does not add a
Windows startup task or change host sleep/reboot settings. See
[Microsoft's WSL systemd boundary](https://learn.microsoft.com/en-us/windows/wsl/systemd/).

Synthetic policy/HTTP/command tests: tests/test_tunnel_guard.py. Real server
installation and current HTTPS state are separate evidence; no production outage
is deliberately created just to demonstrate recovery.

## Optional Mail On URL Change

With explicit owner authorization, install tunnel_mail.py beside the guard and
the separate triton-wms-tunnel-mail.service/.timer. Its timer checks60s after
completion, independent of recovery; mailbox failure cannot stop the guard.
Private /etc/triton-wms-tunnel-mail.json contains enabled, sender, to and cc.
Use real addresses ONLY in this root-owned0600 file, never tracked configuration.
The module defaults to disabled unless enabled is explicitly true. For example:

```json
{"enabled": true, "sender": "sender@example.com", "to": ["owner@example.com"], "cc": ["sender@example.com"]}
```

First activation establishes the verified current URL as a silent baseline.
No welcome message, daily message, unavailable warning or email on recovery to
the SAME URL. A different, healthy URL with fresh guard state must pass another
HTTPS check and match the exact running container generation before notification.
It sends a short HTML link notice via the existing reader Microsoft Mail.Send
authorization/function; no new login, token copied to host or report job involved.
--check-auth checks authorization without sending. Microsoft202 is accepted,
not delivery/read confirmation. No actual mail is needed to test policy.

The private /var/lib/triton-wms-tunnel-mail/deliveries.sqlite3 ledger and OS lock
reserve each transition BEFORE external send. Accepted transitions never repeat
on process/server restart. A newer URL supersedes an older unsent one. Returning
to a previous URL after a real intervening change is another transition. Missing
consent/401/403 or429 pauses15min before retrying the same event; other definite
4xx rejections stop. Timeout,408,5xx,unexpected result or interrupted SENDING
requires REVIEW with no automatic repeat. Inspect the reference in Enviados
before any manual resolution; never delete the ledger to force a send. The
subject is Triton WMS con lector: nuevo enlace disponible and the HTML includes
the event reference, new link and local Lima time, without secrets or old links.

Inspect systemctl status/journalctl for the mail service and the private ledger.
Do not reset the baseline/ledger during code updates or recreate the old daily
Codex automation. Tests: tests/test_tunnel_mail.py, Linux/synthetic mailbox only.
