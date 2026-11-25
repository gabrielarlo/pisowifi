---
description: Rebuild the Orange Pi SD image, bumping its version; add --live to also live-patch a device after the build
---

Rebuild the Piso WiFi SD-card image. Optional live-patch after a successful build.

Arguments: `$ARGUMENTS` — may contain `--live` plus an optional live-patch target and scope.

- `/rebuild` — rebuild only
- `/rebuild --live piso@<host> [--code|--configs|--all]` — rebuild then live-patch that host
- `/rebuild --live` without a host — ask the user for the target before patching; never guess

Steps:

1. Parse `$ARGUMENTS`:
   - If it contains `--live`, extract the target (`piso@...`) and explicit scope (`--code`/`--configs`/`--all`) if given. Strip `--live` and those tokens before any other use so they don't leak into the build command.
   - If `--live` is present but no target was supplied in `$ARGUMENTS`, ask the user for the target (`piso@<device-ip-or-tailnet-host>`) and wait for their reply before continuing past the build.
   - If no `--live` flag is present, this is a build-only run — skip all patch steps.

2. Bump the image version before building. Read `device/version` (one `MAJOR.MINOR.PATCH` line) and
   inspect `git status --short` + `git diff --stat`, excluding `device/version` itself. If nothing
   else changed, skip the bump and say so. Otherwise decide the bump level with Laya first:
   `tools.laya.decide`, choice `patch` / `minor` / `major`, state = changed paths + diff stat,
   criteria: `patch` = bug fix, copy/config tweak, no new behaviour; `minor` = new backward-compatible
   feature/endpoint/UI; `major` = breaking API/schema/auth/security or device networking change.
   Proceed at >= 0.70; at 0.60–0.70 re-judge once; below 0.60 or Laya unavailable, call
   `tools.jev.jev_decide` with the same options and take the higher confidence; still below 0.70,
   ask the user. Print `[LAYA] 0.xx` or `[JEV] 0.xx` and `old → new`. Compute the number
   deterministically (patch: z+1, minor: y+1.0, major: x+1.0.0), save the old line, and write the
   new one to `device/version` before the build so the image carries it. Never let the model invent
   a version string. If the build fails or the user cancels before completion, restore the old line
   rather than burning a number.

3. Rebuild the image from the project root (privileged Docker required — loop devices + armhf binfmt):
   ```bash
   bash scripts/build-image.sh
   ```
   This does: (1) download ARMv7 wheels to `build/wheels`, (2) `npm run build` in `frontend/` to emit `frontend/dist`, (3) `docker run --privileged ... debian:trixie bash /work/scripts/build-image-in-docker.sh` to assemble `build/pisowifi-opi-one.img` + `.sha256`. The build copies `device/version` to `/opt/pisowifi/backend/app/version` in the image. Report the final `build/pisowifi-opi-one.img` path, its `.sha256`, the version shipped, and any failure output. On failure, stop here — do not attempt a live patch and restore the saved old version line.

4. If `--live` was requested and the build succeeded, live-patch the device. Reuse the `deploy` flow for scope + confirmation:
   - If an explicit scope flag was already supplied with `--live`, use it and skip decision.
   - Otherwise inspect `git status --short` and `git diff --stat`: `backend/app/` or frontend sources that feed `frontend/dist` → `--code`; `device/nginx.conf`, `device/dnsmasq-*.conf`, `device/firewall.sh`, `device/sync.sh`, `device/coind.py`, `device/qos.sh` → `--configs`; both → `--all`. Changes outside those paths (systemd units, `scripts/`, `docs/`, requirements) are not patchable live — list them and remind the user they are now baked into the new image but need a reflash for systemd/OS changes.
   - Decide the ambiguity with Laya first, Jev fallback: `tools.laya.decide` with choices `--code`/`--configs`/`--all` (put changed paths in `state`), accept at >= 0.60; fallback to `tools.jev.jev_decide` if unavailable or below 0.60 and take the higher-confidence result; below 0.70 ask the user. Print `[LAYA] 0.xx` or `[JEV] 0.xx`.
   - Show the chosen flag and exact command, then ask for confirmation before mutating the device:
     ```bash
     bash scripts/patch-device.sh <target> <flag>
     ```
     Note that `--code`/`--all` rebuilds `frontend/dist` again (already fresh from step 3), files are staged and uploaded over SSH via a ControlMaster (`-M -S`, `ControlPersist=5m`, one password prompt for `piso` from `/etc/pisowifi/ssh-credentials`), and `piso-patch` (`device/piso-patch`) backs up `backend/app/`, `frontend/dist/`, `/etc/pisowifi/*` with `flock` and rolls back on any failure. `device/version` is always staged as `backend/app/version` so the device reports the same version as the new image, with no reflash.
   - After confirmation, run it from the project root. If the SSH password prompt cannot be satisfied non-interactively, stop and print the exact command for the user to run in their own terminal.
   - Verify from the output: `OK: patch applied` in the tail of `/var/log/piso-patch.log` is success; any `ROLLBACK` or `FAIL` means reverted — report it and do not claim success. Keep the bumped version only when the patch succeeds; if it fails, note that the new image still carries the bumped version.

5. Report what happened:
   - Build-only: image path + sha256, version shipped, and whether `secrets/ssh-credentials` / `secrets/admin-credentials` need refreshing from the new image (mode `0600`) before the next SSH/deploy.
   - With `--live`: both the image result and the patch result (scope, what was deployed, version, anything that still needs a reflash).
