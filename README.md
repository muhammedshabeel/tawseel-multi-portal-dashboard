# Tawseel Multi-Portal Dashboard

A consolidated Streamlit control tower for multiple Tawseel portals. The dashboard reads each portal's current master data from Google Sheets, combines the records, and presents executive metrics, portal comparison, live operations, agent performance, failure analysis, and data-quality checks.

## Architecture

Portal collectors remain separate from the dashboard:

`Tawseel portals -> collector scripts -> Google Sheets -> Streamlit dashboard`

The dashboard is read-only. It must not contain portal passwords or run Playwright scrapers.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml
streamlit run app.py
```

Share every configured Google Sheet with the service-account `client_email` as Viewer or Editor.

## Streamlit Community Cloud

1. Push this repository to GitHub.
2. Open Streamlit Community Cloud.
3. Create an app from this repository, branch `main`, entry file `app.py`.
4. Paste the contents of `.streamlit/secrets.toml` into App Settings > Secrets.
5. Deploy.

## Approval-based updates

Production should deploy from `main`. Build changes on a branch and open a pull request. Merge only after review and approval. Streamlit automatically redeploys after the merge.

## Security

Never commit `.streamlit/secrets.toml`, `.env`, `credentials.json`, portal passwords, or browser storage-state files.
