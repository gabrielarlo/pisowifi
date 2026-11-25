---
description: Patch the live Piso WiFi device over SSH; Laya/Jev pick the scope and version bump from the current changes
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

2. Bump the image version before staging. Read `device/version` (one `MAJOR.MINOR.PATCH` line) and
   use the change list from step 1, excluding `device/version` itself. If nothing else changed, skip
   the bump and say so. Otherwise decide the bump level with Laya first: `tools.laya.decide`,
   choice `patch` / `minor` / `major`, state = changed paths + diff stat, criteria: `patch` = bug
   fix, copy/config tweak, no new behaviour; `minor` = new backward-compatible feature/endpoint/UI;
   `major` = breaking API/schema/auth/security or device networking change. Proceed at >= 0.70; at
   0.60–0.70 re-judge once; below 0.60 or Laya unavailable, call `tools.jev.jev_decide` with the same
   options and take the higher confidence; still below 0.70, ask the user. Print `[LAYA] 0.xx` or
   `[JEV] 0.xx` and `old → new`. Compute the number deterministically (patch: z+1, minor: y+1.0,
   major: x+1.0.0), save the old line, and write the new one to `device/version`. Never let the
   model invent a version string.

3. Before any mutating step, show the chosen flag, the exact command and the version bump, then ask
   the user to confirm:

   ```bash
   bash scripts/patch-device.sh <target> <flag>
   ```

   State that `--code`/`--all` rebuilds `frontend/dist`, files are staged and uploaded over SSH,
   and `piso-patch` backs up and rolls back on failure. `device/version` is always staged as
   `backend/app/version` for every scope — a path the already-deployed `piso-patch` accepts, so no
   reflash is needed. If the user cancels or the patch fails/rolls back, restore the saved old
   `device/version` line rather than burning a number; once `OK: patch applied` is verified, keep it.

4. After confirmation, run it from the project root. The script prompts once for the SSH password
   (from `/etc/pisowifi/ssh-credentials`) and reuses the connection via an SSH ControlMaster. If
   that prompt cannot be satisfied non-interactively, stop retrying and print the exact command
   for the user to run in their own terminal.

5. Verify from the script output: look for `OK: patch applied` in the last lines of
   `/var/log/piso-patch.log`. Any `ROLLBACK` or `FAIL` means the patch was reverted — report it and
   do not claim success. Report the final scope, what was deployed, the version now returned by
   `/api/admin/version`, and anything that still needs an image rebuild.
