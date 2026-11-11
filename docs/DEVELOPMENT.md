# Development and validation

## Test environment

Use Python 3.14 and disposable virtual environments. Never install the test stack into a running Home Assistant environment.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python scripts/run_tests.py -q
```

The fixture package currently pins HA **2026.10.4**. `run_tests.py` loads HA before the test plugins to initialize its HTTP/schema compatibility aliases. Tests use synthetic accounts and mocked portal requests.

Test actual HA **2026.11.1** separately: the older fixture package is not compatible with that core's internal logging helpers.

```sh
python3.14 -m venv /tmp/eac-core-smoke
/tmp/eac-core-smoke/bin/python -m pip install homeassistant==2026.11.1 eac-dso-portal==0.2.1
/tmp/eac-core-smoke/bin/python scripts/smoke_ha.py
```

The smoke check creates a temporary HA configuration and SQLite database, uses a synthetic portal client, verifies recorded statistics and reauthentication, then unloads the integration. It does not target production HA or use DSO credentials.

## Static checks and dependency audit

```sh
.venv/bin/python -m pip install bandit==1.9.4 pip-audit==2.10.1 ruff==0.17.4
.venv/bin/ruff check custom_components tests --select E9,F,I
.venv/bin/ruff format --check custom_components tests
.venv/bin/bandit -r custom_components
.venv/bin/pip-audit -r audit/runtime-resolved.txt --no-deps --disable-pip
bash -n scripts/deploy_smb.sh
git diff --check
```

`audit/runtime-resolved.txt` is a historical runtime dependency snapshot, not a complete HA lockfile. CI also audits a fresh resolution of the requirement in `manifest.json`, so new dependency releases are not hidden by the old snapshot. Neither audit covers every package in a production HA installation.

CI additionally runs hassfest and HACS validation. Actions are pinned to immutable revisions with read-only repository permissions. Audit evidence contains synthetic test results; do not replace it with production exports or tokens.

## Maintenance points

- The client inherits parsing/model methods from `eac-dso-portal==0.2.1` but overrides transport and sanitizes parser failures. Inspect upstream changes before changing the pin.
- Preserve existing entity and statistic IDs to avoid orphaning history.
- Add regression tests for security fixes and changed data semantics.
- Update `manifest.json`, changelog and review evidence together. A local test pass is not a claim that remote CI or every future HA version passes.

## Deployment and rollback

1. Back up HA and record the installed integration version.
2. Install only the component directory from the reviewed revision. Do not upload tests, `.env`, audit reports or private exports.
3. Restart HA and check the integration loads, authentication works and measured timestamps are plausible.
4. Compare one known daily import/export difference with the portal. Check the Energy Dashboard has no duplicate grid series.
5. Roll back by restoring the previous component directory and restarting. Code rollback does not undo statistics already written; use the backup for a complete data rollback.

The optional `scripts/deploy_smb.sh` reads the variables in `.env.example`. It copies files but does not restart HA, create a backup, delete obsolete files or verify installation. It requires `smbclient` on your computer and a configured HA Samba share. The auth file is owner-only and removed on exit; the password is not put in command arguments. Do not run with shell tracing enabled.
