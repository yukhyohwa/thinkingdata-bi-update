# FiveCross TDBI Report Updater

Automatically refreshes a ThinkingData report from a local SQL file. It reuses the data-client browser-session flow: persistent login, session validation, automatic re-login, and a separate session for China and international ThinkingData.

Unlike `fivecross-data-client`, this tool does **not** download query results. It copies the local SQL, selects all old SQL in the editor, pastes over it, calculates it, waits for **全量下载 / Download All** to confirm completion, clicks **更新报表 / Update Report**, then clicks **更新 / Update** in the confirmation dialog. It is also compatible with a first-level **保存报表 / Save Report** button.

## Setup

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Fill the two account credentials in `.env`. The target SQL URL determines which credentials are used. `ss-web.5xgames.com` is treated as China; configured `TA_URL_CN` and `TA_URL_GLOBAL` hosts take precedence. Add unfamiliar domains to `TA_CN_HOSTS` or `TA_GLOBAL_HOSTS`.

## SQL file URL

Put the SQL IDE link near the top of the SQL opening comment:

```sql
/*
URL: https://ss-web.5xgames.com/#/tga/ide/-1?tab=result&panelCreate=22_830
*/
SELECT ...;
```

`-- URL: https://...` works too. The report identified by this URL is the report that will be saved.

Place report SQL files in `input/`. A bare filename is resolved there automatically.

## Run

```powershell
# Optional first login; the browser is shown and its session is saved.
python main.py --login kpi_target_completion.sql

# Refresh the report. Browser stays off-screen by default.
python main.py kpi_target_completion.sql

# Show the browser during the run.
python main.py kpi_target_completion.sql --show
```

The SQL input sequence intentionally uses **copy local SQL → editor Ctrl+A → Ctrl+V**. It does not replace Monaco's document model directly, so ThinkingData's custom parameter settings are not reset.

## Automated Report Update Flow

When you run an update, the tool performs the following steps automatically:

1. Opens the exact ThinkingData SQL IDE URL from the SQL file's opening `URL:` comment.
2. Copies the local SQL file content to the browser clipboard.
3. Selects all SQL currently in the web editor with `Ctrl+A`.
4. Pastes the local SQL over the selected web SQL with `Ctrl+V`, preserving existing custom parameter settings.
5. Clicks **Calculate**.
6. Waits for **Download All** to appear, using it only as confirmation that calculation has completed. It never downloads data.
7. Clicks **Update Report** (or **Save Report** if that is the label in the current ThinkingData UI).
8. Waits for the confirmation dialog.
9. Clicks **Update** in the confirmation dialog.
10. Waits for the dialog to close, then reports that the report update succeeded.
