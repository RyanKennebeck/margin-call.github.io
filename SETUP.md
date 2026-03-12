# CRE Crisis Monitor — Setup Guide

Live dashboard that auto-fetches economic data daily, checks thresholds,
and pushes alerts to your phone via ntfy.sh when conditions change.

**Total setup time: ~15 minutes**

---

## What You Need Before Starting

- A GitHub account (free) — github.com
- A phone with the ntfy app installed (free)
- A FRED API key (free, 2 minutes)

---

## Step 1 — Get Your FRED API Key (2 min)

1. Go to https://fredaccount.stlouisfed.org/login/secure/
2. Create a free account
3. Go to "API Keys" in your account dashboard
4. Click "Request API Key"
5. Copy the key — you'll need it in Step 4

---

## Step 2 — Set Up ntfy.sh on Your Phone (3 min)

1. Download the **ntfy** app:
   - iOS: https://apps.apple.com/app/ntfy/id1625396347
   - Android: https://play.google.com/store/apps/details?id=io.heckel.ntfy

2. Create a private topic name — make it hard to guess, like:
   `crisis-monitor-[your initials]-[random number]`
   Example: `crisis-monitor-jd-7734`

3. In the ntfy app, tap "+" and subscribe to your topic name

4. Save your topic name — you'll need it in Step 4

---

## Step 3 — Create Your GitHub Repository (3 min)

1. Go to github.com and sign in
2. Click "+" → "New repository"
3. Name it: `crisis-monitor`
4. Set to **Private**
5. Click "Create repository"
6. Upload all files from this folder to the repo:
   - index.html
   - data.json
   - alert_state.json (create empty: `{}`)
   - scripts/fetch_data.py
   - .github/workflows/update.yml

   Easiest way: drag and drop files into the GitHub web interface,
   or use GitHub Desktop app.

---

## Step 4 — Add Secrets to GitHub (3 min)

Your API key and ntfy topic must be stored as GitHub Secrets
(never commit them in code).

1. In your repo, go to: **Settings → Secrets and variables → Actions**
2. Click "New repository secret"
3. Add these two secrets:

   **Secret 1:**
   - Name:  `FRED_API_KEY`
   - Value: (your FRED API key from Step 1)

   **Secret 2:**
   - Name:  `NTFY_TOPIC`
   - Value: (your ntfy topic name from Step 2, e.g. `crisis-monitor-jd-7734`)

---

## Step 5 — Enable GitHub Pages (2 min)

1. In your repo, go to: **Settings → Pages**
2. Under "Source", select: **Deploy from a branch**
3. Branch: `main`, Folder: `/ (root)`
4. Click Save
5. Your dashboard will be live at:
   `https://[your-github-username].github.io/crisis-monitor/`

---

## Step 6 — Run the First Update (1 min)

The action runs automatically every day at 07:00 UTC, but run it
manually now to populate data.json immediately:

1. Go to your repo → **Actions** tab
2. Click "CRE Crisis Monitor — Daily Update" on the left
3. Click "Run workflow" → "Run workflow" (green button)
4. Watch it run — takes about 30–60 seconds
5. Refresh your GitHub Pages URL — live data will appear

---

## Step 7 — Update Manual Indicators (10 min, quarterly)

Three indicators require manual updates because no free API exists:

### 1. Office Vacancy Rate
- Go to: https://www.cbre.com/insights/figures/office-figures
- Download the latest "US Office Figures" PDF
- Find "National Vacancy Rate" (usually on page 1)
- In your repo, edit `data.json`
- Find `"office_vacancy"` → `"value"` → replace `null` with the number
- Also update `"last_updated"` to today's date in ISO format
- Commit the change

### 2. Shiller CAPE Ratio
- Go to: https://www.multpl.com/shiller-pe
- The current value is displayed at the top of the page
- Edit `data.json` → `"cape_ratio"` → `"value"`
- Commit the change

### 3. Regional Bank Loan Loss Provisions
- Go to: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=10-Q
- Search for each: KEY, RF, TFC, NYCB
- Open their latest 10-Q filing
- Find "Provision for Credit Losses" in the income statement
- Compare to the prior quarter's 10-Q
- Calculate: ((new - old) / old) * 100 = % change
- Enter the highest % change among the four banks
- Edit `data.json` → `"regional_bank_provisions"` → `"value"`
- Commit the change

**You will receive a ntfy.sh notification reminding you to do this:**
- CAPE Ratio: 1st of every month
- Office Vacancy + Bank Provisions: 1st of Jan, Apr, Jul, Oct

---

## How Alerts Work

| Threshold Crossed | What Happens |
|---|---|
| WATCH | Low-priority ntfy push notification |
| DANGER | High-priority ntfy push notification |
| CRITICAL | Urgent ntfy push notification, repeats daily until resolved |
| RECOVERED | Confirmation notification when indicator returns to SAFE |
| Manual reminder | Quarterly ntfy push asking you to update manual indicators |

**Anti-spam logic:** The system will not re-alert you for the same
threshold. It only alerts again when the status *worsens* to the
next tier, or when a CRITICAL indicator is still critical the next day.

---

## Updating Thresholds

All thresholds are defined in `scripts/fetch_data.py` under the
`INDICATORS` dictionary. Find the indicator you want to adjust and
change the threshold values. Commit the change and the next run
will use the new thresholds.

---

## Cost Summary

| Item | Cost |
|---|---|
| GitHub (private repo) | Free |
| GitHub Actions (daily cron) | Free (~60 min/month, limit is 2000) |
| GitHub Pages (hosting) | Free |
| FRED API | Free |
| ntfy.sh | Free |
| **Total** | **$0/month** |

---

## Troubleshooting

**Dashboard shows "FAILED TO LOAD DATA"**
→ Run the GitHub Action manually (Step 6). data.json needs to be
  populated at least once before the dashboard can display anything.

**Not receiving ntfy notifications**
→ Check that NTFY_TOPIC secret exactly matches your subscribed topic
→ Make sure ntfy app notifications are enabled in your phone settings

**GitHub Action failing**
→ Go to Actions tab, click the failed run, read the error log
→ Most common cause: FRED_API_KEY secret not set correctly

**Data showing as "unknown"**
→ Normal on first run. After the Action runs successfully, all
  auto indicators will have real values within 60 seconds.
