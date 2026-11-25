# Plan: console version tied to image build version

## Goal

One version number (`MAJOR.MINOR.PATCH`) that is baked into every SD image, pushed by every live
patch, returned by the backend, and shown in the admin console. `/rebuild` and `/deploy` bump it
before doing their work; Laya (Jev fallback) chooses patch / minor / major from the diff.

## Files to reach

| Path | Change |
|---|---|
| `device/version` (new) | Single source of truth, one line, e.g. `1.0.0` |
| `scripts/build-image-in-docker.sh` | After the backend copy: `cp /work/device/version "$ROOTFS/opt/pisowifi/backend/app/version"` |
| `scripts/verify-image.sh` | Assert `/opt/pisowifi/backend/app/version` exists and matches `^[0-9]+\.[0-9]+\.[0-9]+$` |
| `scripts/patch-device.sh` | Always stage `device/version` as `$STAGE/backend/app/version`, for every scope (including `--configs`) |
| `tests/test_patch.sh` | Case 6: stage `backend/app/version`, assert it lands at `/opt/pisowifi/backend/app/version` and `pisowifi-app` restart is logged |
| `backend/app/config.py` | `image_version()` reads `PISO_VERSION_PATH` (default `/opt/pisowifi/backend/app/version`), falls back to repo `device/version`, then `"dev"` |
| `backend/app/main.py` | `GET /api/admin/version` behind `require_admin` → `{"version": "1.0.0"}` |
| `backend/tests/test_api.py` | 401 without token; returns version from the configured file |
| `frontend/src/views/AdminView.vue` | Fetch version once after login; append `vX.Y.Z` to the header title line (visible at 390px) |
| `.opencode/commands/rebuild.md`, `.opencode/commands/deploy.md` | Version-bump step using Laya/Jev; include bump in confirmation/report and revert on failure |
| `AGENTS.md` | One line: `device/version` is the source; installed at `backend/app/version`, bumped by the commands |

`device/piso-patch` is **not** edited: `backend/app/*` is already allowed and maps to a
`pisowifi-app` restart, so devices already in the field accept the new file with no reflash.

## Decisions fixed up front

- **Where the number lives on the device:** `/opt/pisowifi/backend/app/version`, not
  `/etc/pisowifi/version`. The old `piso-patch` allow-list (`device/piso-patch:70`) already accepts
  `backend/app/*`; adding a new config path would make every deploy to a non-reflashed device
  `ROLLBACK`. Confirmed with the user: no reflash required.
- **Reading:** read the file per request (tiny, and a config-only patch then needs no app restart,
  though `pisowifi-app` is restarted anyway by the `backend/app/*` mapping). Fallback order keeps
  host dev and tests working without a device file.
- **Exposure:** dedicated admin endpoint, not folded into `/api/admin/password-status` — keeps
  version independent of the default-password warning and independently testable.
- **Display:** muted `v{{ version }}` span beside the header title at `AdminView.vue:381`, in a
  `flex min-w-0` wrapper with `shrink-0` on the version so it stays visible at 390px while the title
  itself truncates (the "Admin" badge and second info line are `hidden … sm:`). Verified in browser.
- **Bump rule (commands):** read `device/version`, collect `git status --short` + `git diff --stat`
  (excluding `device/version` itself), ask Laya `choice` with `patch` / `minor` / `major`:
  - `patch` — bug fix, copy/config tweak, small correction, no new behaviour
  - `minor` — new backward-compatible feature/endpoint/UI
  - `major` — breaking API/schema/auth/security or device networking change
  Laya first: proceed at ≥ 0.70; at 0.60–0.70 re-judge once (Jev fallback) and proceed only if the
  better result is ≥ 0.70; < 0.60 or Laya unavailable → call `tools.jev.jev_decide` with the same
  options, take the higher confidence, proceed only if ≥ 0.70; otherwise ask the user. Print
  `[LAYA] 0.xx` / `[JEV] 0.xx` and `old → new`. Compute `major.minor.patch+1` /
  `major.minor+1.0` / `major+1.0.0`, write one line. If there are no changes beyond the version
  file, skip the bump and say so. Laya/Jev pick the *level*; the arithmetic stays deterministic.
- **Order and failure:** bump before `scripts/build-image.sh` (`/rebuild`) and before staging files
  (`/deploy`, `/rebuild --live`), so image and device both carry the new number. Save the old line
  first; if the build fails or the deploy is cancelled/rejected before completion, restore the old
  line rather than burning a number. If the patch succeeds, keep the bump. Show the bump in the
  existing confirmation prompt.
- **Scope:** `/deploy` scope classification is unchanged; `device/version` is always staged
  regardless of `--code`/`--configs`/`--all`.

## Verification

- `backend/`: `../.venv/bin/python -m pytest tests -q` — existing suite plus new version tests.
- `frontend/`: `npm run build`; browser MCP at 390×844 and 1200×900 — version visible in the title,
  no horizontal scroll, header controls still fit on phone.
- `bash tests/test_patch.sh` — includes the new `backend/app/version` staging case; confirm no
  rollback and the expected restart.
- `bash scripts/verify-image.sh` against the current `build/` image if one exists; otherwise note it
  needs a rebuild. A full `/rebuild` needs privileged Docker (loop devices) — do not run it just to
  test the version wiring.
- Manual command dry-read: confirm both command docs describe the bump before build/stage, the
  revert-on-failure rule, and Laya/Jev thresholds matching this plan.
