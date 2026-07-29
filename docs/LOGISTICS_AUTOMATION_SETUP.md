# Logistics Automation Setup

The Logistics Recovery automation is isolated from all other Tawseel dashboards and operational tabs.

## One-time GitHub secret

Create one encrypted repository secret:

- Name: `STREAMLIT_SECRETS_TOML`
- Value: the complete production `.streamlit/secrets.toml` content currently used by the deployed Streamlit app.

GitHub path:

`Repository -> Settings -> Secrets and variables -> Actions -> New repository secret`

Do not commit the production secrets file to the repository.

## Automatic schedule

The workflow `.github/workflows/logistics-auto-sync.yml` runs every 10 minutes.

It can also run immediately after an external Tawseel collector sends a GitHub `repository_dispatch` event with type:

`Tawseel-refresh-complete`

## Automatic behavior

Each successful run:

1. Reads all latest Tawseel source-sheet records.
2. Refreshes every case already assigned to Logistics.
3. Detects new critical or follow-up orders.
4. Creates one stable case per Portal + AWB.
5. Assigns new cases using the saved round-robin cursor.
6. Reopens a previously closed case for the same agent if it becomes critical again.
7. Preserves agent activity, remarks, calls and audit history.
8. Records courier status changes in `LOGISTICS_STATUS_UPDATES`.
9. Updates `LOGISTICS_AUTOMATION_HEALTH`.
10. Mirrors changed logistics data to the independent backup spreadsheet.

## Reliability controls

- GitHub Actions concurrency prevents overlapping scheduled jobs.
- Spreadsheet health lease prevents a second automated process from starting during an active run.
- Stable case IDs prevent duplicate assignments.
- Four retry attempts use exponential backoff.
- A recent-success throttle reduces Google Sheets quota usage.
- Automation health and errors are stored in Google Sheets.
- Backup errors are reported separately and do not undo a successful logistics assignment.

## Verification

After adding the secret:

1. Open `Actions -> Logistics Auto Sync`.
2. Select `Run workflow`.
3. Enable `Force sync` for the first run.
4. Confirm the workflow succeeds.
5. Open `LOGISTICS_AUTOMATION_HEALTH` and confirm `Status` is `SUCCESS`.
