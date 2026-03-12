#!/usr/bin/env python3
"""
CRE Crisis Monitor — Data Fetcher
Runs daily via GitHub Actions.
Fetches FRED API data, checks thresholds, sends ntfy.sh alerts.
"""

import json
import os
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
import sys

# ─────────────────────────────────────────────
# CONFIG — set these as GitHub Actions secrets
# ─────────────────────────────────────────────
FRED_API_KEY   = os.environ.get("FRED_API_KEY", "")
NTFY_TOPIC     = os.environ.get("NTFY_TOPIC", "")      # e.g. "crisis-monitor-abc123"
NTFY_URL       = f"https://ntfy.sh/{NTFY_TOPIC}"

# Path to state file (tracks last alert sent to prevent spam)
STATE_FILE  = os.path.join(os.path.dirname(__file__), "..", "alert_state.json")
DATA_FILE   = os.path.join(os.path.dirname(__file__), "..", "data.json")

# ─────────────────────────────────────────────
# THRESHOLDS
# Each indicator has: safe, watch, danger, critical
# Values are the UPPER bound of each tier
# ─────────────────────────────────────────────
INDICATORS = {

    # ── TIER 1: EARLY WARNING ──────────────────────────────────────────────

    "hy_spread": {
        "name": "High-Yield Bond Spread (OAS)",
        "fred_series": "BAMLH0A0HYM2",
        "unit": "bps",
        "description": "Spread between junk bonds and Treasuries. Rising = credit stress.",
        "tier": 1,
        "tier_label": "Early Warning",
        "direction": "higher_is_worse",
        "thresholds": {
            "safe":     300,
            "watch":    450,
            "danger":   650,
            "critical": 900,
        },
        "manual": False,
        "source_url": "https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
    },

    "ig_spread": {
        "name": "Investment Grade Corporate Spread (OAS)",
        "fred_series": "BAMLC0A0CM",
        "unit": "bps",
        "description": "Spread between IG corporate bonds and Treasuries. Spike = contagion leaving CRE.",
        "tier": 3,
        "tier_label": "Systemic",
        "direction": "higher_is_worse",
        "thresholds": {
            "safe":     120,
            "watch":    200,
            "danger":   350,
            "critical": 500,
        },
        "manual": False,
        "source_url": "https://fred.stlouisfed.org/series/BAMLC0A0CM",
    },

    "cre_delinquency": {
        "name": "CRE Loan Delinquency Rate",
        "fred_series": "DRCRELEXFACBS",
        "unit": "%",
        "description": "% of commercial real estate loans 30+ days past due at banks.",
        "tier": 1,
        "tier_label": "Early Warning",
        "direction": "higher_is_worse",
        "thresholds": {
            "safe":     3.0,
            "watch":    5.0,
            "danger":   8.0,
            "critical": 12.0,
        },
        "manual": False,
        "source_url": "https://fred.stlouisfed.org/series/DRCRELEXFACBS",
    },

    "auto_delinquency": {
        "name": "Auto Loan Delinquency Rate (90+ days)",
        "fred_series": "DRAUTACBS",
        "unit": "%",
        "description": "% of auto loans 90+ days past due. Consumer stress leading indicator.",
        "tier": 2,
        "tier_label": "Concurrent",
        "direction": "higher_is_worse",
        "thresholds": {
            "safe":     2.0,
            "watch":    3.5,
            "danger":   5.0,
            "critical": 7.0,
        },
        "manual": False,
        "source_url": "https://fred.stlouisfed.org/series/DRAUTACBS",
    },

    "yield_curve": {
        "name": "Yield Curve (10yr minus 2yr Treasury)",
        "fred_series": "T10Y2Y",
        "unit": "%",
        "description": "Negative = inverted = recession signal. Re-inversion after Fed cuts = market rejects rescue.",
        "tier": 3,
        "tier_label": "Systemic",
        "direction": "lower_is_worse",
        "thresholds": {
            "safe":      1.0,
            "watch":     0.0,
            "danger":   -0.5,
            "critical": -1.0,
        },
        "manual": False,
        "source_url": "https://fred.stlouisfed.org/series/T10Y2Y",
    },

    "m2_growth": {
        "name": "US M2 Money Supply YoY Growth",
        "fred_series": "M2SL",
        "unit": "%",
        "description": "Rate of change in broad money supply. Extremes in either direction are danger signals.",
        "tier": 3,
        "tier_label": "Systemic",
        "direction": "both_extremes_worse",
        "thresholds": {
            "safe":     7.0,
            "watch":    10.0,
            "danger":   15.0,
            "critical": 20.0,
            "safe_low":    2.0,
            "watch_low":   0.0,
            "danger_low": -2.0,
        },
        "manual": False,
        "source_url": "https://fred.stlouisfed.org/series/M2SL",
    },

    "fed_funds_rate": {
        "name": "Federal Funds Rate",
        "fred_series": "FEDFUNDS",
        "unit": "%",
        "description": "Current Fed rate. High-for-longer = debt servicing costs balloon.",
        "tier": 3,
        "tier_label": "Systemic",
        "direction": "context",
        "thresholds": {
            "safe":     2.5,
            "watch":    4.0,
            "danger":   5.0,
            "critical": 6.0,
        },
        "manual": False,
        "source_url": "https://fred.stlouisfed.org/series/FEDFUNDS",
    },

    # ── MANUAL INDICATORS (quarterly human update required) ──────────────

    "office_vacancy": {
        "name": "Office Vacancy Rate (Major Markets)",
        "fred_series": None,
        "unit": "%",
        "description": "% of commercial office space empty in major metros. Source: CBRE quarterly report.",
        "tier": 2,
        "tier_label": "Concurrent",
        "direction": "higher_is_worse",
        "thresholds": {
            "safe":     15.0,
            "watch":    22.0,
            "danger":   27.0,
            "critical": 30.0,
        },
        "manual": True,
        "manual_source": "https://www.cbre.com/insights/figures/office-figures",
        "manual_instructions": "Download the latest CBRE US Office Figures PDF. Find the 'National Vacancy Rate' figure. Update this value.",
        "update_frequency_days": 90,
        "source_url": "https://www.cbre.com/insights/figures/office-figures",
    },

    "cape_ratio": {
        "name": "Shiller CAPE Ratio (S&P 500)",
        "fred_series": None,
        "unit": "x",
        "description": "Cyclically-adjusted P/E. High = thin cushion before correction becomes catastrophic.",
        "tier": 3,
        "tier_label": "Systemic",
        "direction": "higher_is_worse",
        "thresholds": {
            "safe":     20.0,
            "watch":    30.0,
            "danger":   38.0,
            "critical": 44.0,
        },
        "manual": True,
        "manual_source": "https://www.multpl.com/shiller-pe",
        "manual_instructions": "Visit multpl.com/shiller-pe. The current value is displayed at the top of the page. Update this value.",
        "update_frequency_days": 30,
        "source_url": "https://www.multpl.com/shiller-pe",
    },

    "regional_bank_provisions": {
        "name": "Regional Bank Loan Loss Provisions (QoQ Change)",
        "fred_series": None,
        "unit": "%",
        "description": "% QoQ increase in loan loss provisions for KEY, RF, TFC, NYCB. Banks quietly admitting loans are bad.",
        "tier": 1,
        "tier_label": "Early Warning",
        "direction": "higher_is_worse",
        "thresholds": {
            "safe":     20.0,
            "watch":    50.0,
            "danger":   100.0,
            "critical": 150.0,
        },
        "manual": True,
        "manual_source": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=10-Q",
        "manual_instructions": "Search SEC EDGAR for 10-Q filings from KEY, RF, TFC, NYCB. Find 'Provision for Credit Losses' table. Compare to prior quarter and calculate % change. Enter the highest % change among the four banks.",
        "update_frequency_days": 90,
        "source_url": "https://www.sec.gov/cgi-bin/browse-edgar",
    },
}

# ─────────────────────────────────────────────
# MANUAL UPDATE REMINDER SCHEDULE
# ─────────────────────────────────────────────
QUARTERLY_REMINDER_MONTHS = [1, 4, 7, 10]   # Jan, Apr, Jul, Oct
MONTHLY_REMINDER_DAYS     = [1]              # 1st of each month for CAPE

# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def http_get(url: str, headers: dict = None) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def send_ntfy(title: str, message: str, priority: str = "default", tags: list = None):
    """Send a push notification via ntfy.sh."""
    if not NTFY_TOPIC:
        print(f"[NTFY SKIP] No topic set. Would have sent: {title} — {message}")
        return
    payload = json.dumps({
        "topic":    NTFY_TOPIC,
        "title":    title,
        "message":  message,
        "priority": priority,          # min/low/default/high/urgent
        "tags":     tags or [],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://ntfy.sh",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[NTFY OK] {title}")
    except Exception as e:
        print(f"[NTFY ERROR] {e}")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"indicators": {}, "last_updated": None, "meta": {}}

# ─────────────────────────────────────────────
# FRED FETCHER
# ─────────────────────────────────────────────

def fetch_fred_series(series_id: str, is_yoy: bool = False) -> dict:
    """Fetch latest value from FRED. Returns {value, date, previous_value}."""
    # Fetch last 14 months to allow YoY calculation
    obs_start = (datetime.now() - timedelta(days=430)).strftime("%Y-%m-%d")
    params = urllib.parse.urlencode({
        "series_id":       series_id,
        "api_key":         FRED_API_KEY,
        "file_type":       "json",
        "sort_order":      "desc",
        "observation_start": obs_start,
        "limit":           50,
    })
    url = f"https://api.stlouisfed.org/fred/series/observations?{params}"
    try:
        raw = http_get(url)
        data = json.loads(raw)
        obs = [o for o in data.get("observations", []) if o["value"] != "."]
        if not obs:
            return {"value": None, "date": None, "previous_value": None, "error": "No data"}

        latest = obs[0]
        value  = float(latest["value"])
        date   = latest["date"]

        prev_value = float(obs[1]["value"]) if len(obs) > 1 else None

        # YoY calculation for M2
        yoy_value = None
        if is_yoy and len(obs) >= 13:
            old = float(obs[12]["value"])
            yoy_value = round((value - old) / old * 100, 2)

        return {
            "value":          yoy_value if is_yoy else round(value, 2),
            "raw_value":      round(value, 2),
            "date":           date,
            "previous_value": round(prev_value, 2) if prev_value else None,
        }
    except Exception as e:
        return {"value": None, "date": None, "previous_value": None, "error": str(e)}

# ─────────────────────────────────────────────
# THRESHOLD EVALUATOR
# ─────────────────────────────────────────────

def evaluate_threshold(key: str, indicator: dict, value: float) -> str:
    """Returns: safe | watch | danger | critical"""
    t = indicator["thresholds"]
    direction = indicator["direction"]

    if direction == "higher_is_worse":
        if value >= t["critical"]: return "critical"
        if value >= t["danger"]:   return "danger"
        if value >= t["watch"]:    return "watch"
        return "safe"

    elif direction == "lower_is_worse":
        if value <= t["critical"]: return "critical"
        if value <= t["danger"]:   return "danger"
        if value <= t["watch"]:    return "watch"
        return "safe"

    elif direction == "both_extremes_worse":
        # High side
        if value >= t["critical"]: return "critical"
        if value >= t["danger"]:   return "danger"
        if value >= t["watch"]:    return "watch"
        # Low side
        if "danger_low" in t and value <= t["danger_low"]: return "danger"
        if "watch_low"  in t and value <= t["watch_low"]:  return "watch"
        if "safe_low"   in t and value <= t["safe_low"]:   return "watch"
        return "safe"

    return "safe"  # context indicators — don't auto-alert

# ─────────────────────────────────────────────
# ALERT LOGIC
# ─────────────────────────────────────────────

PRIORITY_MAP = {
    "watch":    ("low",    "📊", "warning"),
    "danger":   ("high",   "⚠️",  "rotating_light"),
    "critical": ("urgent", "🚨", "sos"),
}

def maybe_alert(key: str, indicator: dict, status: str, value: float, state: dict):
    """Send alert only if status worsened since last alert."""
    STATUS_RANK = {"safe": 0, "watch": 1, "danger": 2, "critical": 3}
    prev_status = state.get(key, {}).get("last_alerted_status", "safe")

    if STATUS_RANK.get(status, 0) <= STATUS_RANK.get(prev_status, 0):
        # Same or better — no alert (unless critical, repeat daily)
        if status == "critical" and prev_status == "critical":
            last_alert_date = state.get(key, {}).get("last_alert_date", "")
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if last_alert_date == today:
                return  # Already alerted today
        else:
            return

    if status == "safe":
        # Recovery notification
        send_ntfy(
            title=f"✅ RECOVERED: {indicator['name']}",
            message=f"Now at {value} {indicator['unit']} — back to SAFE territory.",
            priority="low",
            tags=["white_check_mark"],
        )
    elif status in PRIORITY_MAP:
        priority, emoji, tag = PRIORITY_MAP[status]
        send_ntfy(
            title=f"{emoji} {status.upper()}: {indicator['name']}",
            message=(
                f"Current value: {value} {indicator['unit']}\n"
                f"Threshold crossed: {status.upper()}\n"
                f"What this means: {indicator['description']}\n"
                f"Source: {indicator['source_url']}"
            ),
            priority=priority,
            tags=[tag, f"tier_{indicator['tier']}"],
        )

    # Update state
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if key not in state:
        state[key] = {}
    state[key]["last_alerted_status"] = status
    state[key]["last_alert_date"]     = today

# ─────────────────────────────────────────────
# MANUAL UPDATE REMINDERS
# ─────────────────────────────────────────────

def check_manual_reminders(data: dict, state: dict):
    """Send reminders to update manual indicators on schedule."""
    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    for key, indicator in INDICATORS.items():
        if not indicator.get("manual"):
            continue

        freq_days = indicator.get("update_frequency_days", 90)
        reminder_key = f"manual_reminder_{key}"

        # Check when last reminder was sent
        last_reminder = state.get(reminder_key, {}).get("last_date", "2000-01-01")
        last_dt = datetime.strptime(last_reminder, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days_since = (now - last_dt).days

        should_remind = False

        if freq_days == 30 and now.day in MONTHLY_REMINDER_DAYS:
            should_remind = True
        elif freq_days == 90 and now.month in QUARTERLY_REMINDER_MONTHS and now.day == 1:
            should_remind = True
        elif days_since >= freq_days:
            # Fallback: remind if overdue regardless of calendar
            should_remind = True

        if should_remind and last_reminder != today:
            # Get last known value from data
            last_value = data.get("indicators", {}).get(key, {}).get("value", "unknown")
            last_updated = data.get("indicators", {}).get(key, {}).get("last_updated", "never")

            send_ntfy(
                title=f"📋 MANUAL UPDATE NEEDED: {indicator['name']}",
                message=(
                    f"This indicator requires a manual update.\n\n"
                    f"Last value: {last_value} {indicator.get('unit','')}\n"
                    f"Last updated: {last_updated}\n\n"
                    f"HOW TO UPDATE:\n{indicator['manual_instructions']}\n\n"
                    f"Source: {indicator['manual_source']}\n\n"
                    f"Once you have the value, edit data.json → indicators → {key} → value"
                ),
                priority="default",
                tags=["memo", "spiral_notepad"],
            )

            if reminder_key not in state:
                state[reminder_key] = {}
            state[reminder_key]["last_date"] = today
            print(f"[REMINDER SENT] {indicator['name']}")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"CRE Crisis Monitor — {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}\n")

    if not FRED_API_KEY:
        print("ERROR: FRED_API_KEY not set. Exiting.")
        sys.exit(1)

    state = load_state()
    data  = load_data()

    if "indicators" not in data:
        data["indicators"] = {}
    if "meta" not in data:
        data["meta"] = {}

    alerts_fired = []

    for key, indicator in INDICATORS.items():
        print(f"Processing: {indicator['name']}")

        if indicator.get("manual"):
            # Don't overwrite manually-set values — just preserve them
            if key not in data["indicators"]:
                data["indicators"][key] = {
                    "value":        None,
                    "status":       "unknown",
                    "manual":       True,
                    "last_updated": None,
                    "unit":         indicator["unit"],
                    "name":         indicator["name"],
                    "description":  indicator["description"],
                    "tier":         indicator["tier"],
                    "tier_label":   indicator["tier_label"],
                    "source_url":   indicator["source_url"],
                    "thresholds":   indicator["thresholds"],
                    "direction":    indicator["direction"],
                    "manual_instructions": indicator.get("manual_instructions", ""),
                    "manual_source":       indicator.get("manual_source", ""),
                }
            else:
                # Re-evaluate threshold on existing value in case thresholds changed
                existing = data["indicators"][key]
                if existing.get("value") is not None:
                    status = evaluate_threshold(key, indicator, existing["value"])
                    existing["status"] = status
                    maybe_alert(key, indicator, status, existing["value"], state)
            print(f"  → Manual indicator, preserved existing value")
            continue

        # Auto-fetch from FRED
        is_yoy = key == "m2_growth"
        result = fetch_fred_series(indicator["fred_series"], is_yoy=is_yoy)

        if result.get("error"):
            print(f"  → ERROR: {result['error']}")
            if key in data["indicators"]:
                data["indicators"][key]["fetch_error"] = result["error"]
            continue

        value = result["value"]
        if value is None:
            print(f"  → No value returned")
            continue

        status = evaluate_threshold(key, indicator, value)
        print(f"  → Value: {value} {indicator['unit']} | Status: {status.upper()}")

        # Alert if threshold crossed
        if indicator["direction"] != "context":
            maybe_alert(key, indicator, status, value, state)
            if status != "safe":
                alerts_fired.append(f"{indicator['name']}: {status.upper()} ({value} {indicator['unit']})")

        # Write to data
        data["indicators"][key] = {
            "value":          value,
            "raw_value":      result.get("raw_value", value),
            "previous_value": result.get("previous_value"),
            "date":           result.get("date"),
            "status":         status,
            "manual":         False,
            "last_updated":   datetime.now(timezone.utc).isoformat(),
            "unit":           indicator["unit"],
            "name":           indicator["name"],
            "description":    indicator["description"],
            "tier":           indicator["tier"],
            "tier_label":     indicator["tier_label"],
            "source_url":     indicator["source_url"],
            "thresholds":     indicator["thresholds"],
            "direction":      indicator["direction"],
        }

    # Check manual update reminders
    print("\nChecking manual update reminders...")
    check_manual_reminders(data, state)

    # Send daily summary if any alerts fired
    if alerts_fired:
        send_ntfy(
            title=f"📊 Daily Summary — {len(alerts_fired)} Active Alert(s)",
            message="\n".join(alerts_fired),
            priority="high",
            tags=["bar_chart"],
        )

    # Update metadata
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data["meta"] = {
        "total_indicators":    len(INDICATORS),
        "auto_indicators":     sum(1 for i in INDICATORS.values() if not i.get("manual")),
        "manual_indicators":   sum(1 for i in INDICATORS.values() if i.get("manual")),
        "active_alerts":       len(alerts_fired),
        "crisis_sequence_step": compute_sequence_step(data),
    }

    # Save files
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

    save_state(state)

    print(f"\n✅ Done. Data written to data.json")
    print(f"Active alerts: {len(alerts_fired)}")


def compute_sequence_step(data: dict) -> int:
    """
    Estimate which step of the 6-step crisis sequence we're in.
    1: CMBS spreads widen  2: Banks take provisions  3: Distressed sales
    4: Vacancy confirms    5: Credit tightens        6: Fed emergency cuts
    """
    indicators = data.get("indicators", {})

    def status_of(key):
        return indicators.get(key, {}).get("status", "safe")

    step = 1
    if status_of("hy_spread") in ("watch", "danger", "critical"):
        step = max(step, 2)
    if status_of("regional_bank_provisions") in ("danger", "critical"):
        step = max(step, 2)
    if status_of("cre_delinquency") in ("danger", "critical"):
        step = max(step, 3)
    if status_of("office_vacancy") in ("danger", "critical"):
        step = max(step, 4)
    if status_of("ig_spread") in ("danger", "critical"):
        step = max(step, 5)
    if status_of("yield_curve") == "critical" and status_of("ig_spread") == "critical":
        step = 6

    return step


if __name__ == "__main__":
    main()
