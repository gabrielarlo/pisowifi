---
description: Patch the live Piso WiFi device over SSH; Laya/Jev pick the scope from the current changes
---

Deploy the current working-tree changes to a live Piso WiFi device using this repo's patch flow.

Target: $ARGUMENTS — expected `piso@<device-ip-or-tailnet-host>`. If empty, ask the user for the
target before doing anything; never guess a host. If an explicit scope (`--all`, `--code`, or
`--configs`) is also supplied, use it and skip the decision step.

1. Inspect `git status --short` (including untracked paths) and `git diff --stat` from the project
   root. Classify the changes:
   - `backend/app/` or frontend sources that feed `frontend/dist` → `--code`
   - `device/nginx.conf`, `device/dnsmasq-*.conf`, `device/firewall.sh`, `device/sync.sh`,
     `device/coind.py` → `--configs`
   - both → `--all`
   Changes outside those paths (systemd units, `scripts/`, `docs/`, requirements, image build) are
   not patchable live — list them and remind the user they need an image rebuild + reflash
   (`docs/FLASH.md`). They do not change the flag.

2. Decide the scope with Laya first, Jev fallback. In `execute`, call `tools.laya.decide` with
   choices `--code`, `--configs`, `--all` and explicit criteria: `--code` = only backend/app or
   frontend sources changed; `--configs` = only device config files changed; `--all` = both.
   Put the changed paths from step 1 in `state`. Accept Laya at confidence >= 0.60; if Laya is
   unavailable or below 0.60, call `tools.jev.jev_decide` with the same options and take the
   higher-confidence result. If neither reaches 0.70, ask the user. This classification is
   mechanical — Jev is usually the authoritative one. Print one status line: `[LAYA] 0.xx` or
   `[JEV] 0.xx`.

3. Before any mutating step, show the chosen flag and the exact command, then ask the user to
   confirm:

   ```bash
   bash scripts/patch-device.sh <target> <flag>
   ```

   State that `--code`/`--all` rebuilds `frontend/dist`, files are staged and uploaded over SSH,
   and `piso-patch` backs up and rolls back on failure.

4. After confirmation, run it from the project root. The script prompts once for the SSH password
   (from `/etc/pisowifi/ssh-credentials`) and reuses the connection via an SSH ControlMaster. If
   that prompt cannot be satisfied non-interactively, stop retrying and print the exact command
   for the user to run in their own terminal.

5. Verify from the script output: look for `OK: patch applied` in the last lines of
   `/var/log/piso-patch.log`. Any `ROLLBACK` or `FAIL` means the patch was reverted — report it and
   do not claim success. Report the final scope, what was deployed, and anything that still needs
   an image rebuild.
