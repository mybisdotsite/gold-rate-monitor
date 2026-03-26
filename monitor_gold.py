import json
import os
import re
import sys
import time
from datetime import datetime

import pytz
import requests
from bs4 import BeautifulSoup

# ============================================================================
# CONSTANTS
# ============================================================================

IST = pytz.timezone("Asia/Kolkata")
DERIVED_KERALA_SOURCE = "AKGSMA_DERIVED"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


# ============================================================================
# LOGGING
# ============================================================================

def log(message, source="SYSTEM"):
    """Timestamped logger for console output."""
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"[{timestamp}] [{source}] {message}")


# ============================================================================
# HISTORY HELPERS
# ============================================================================

def empty_history_state():
    return {
        "last_rates": {},
        "history": [],
        "last_updated": None,
        "consecutive_failures": 0,
    }


def load_history(filename):
    """Safely load JSON history. Returns clean default on any error."""
    if not os.path.exists(filename):
        return empty_history_state()

    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("last_rates", {})
        data.setdefault("history", [])
        data.setdefault("last_updated", None)
        data.setdefault("consecutive_failures", 0)
        return data
    except Exception as e:
        log(f"Could not read {filename}: {e}; using fresh state", "SYSTEM")
        return empty_history_state()


def save_history(filename, data):
    """Safely save JSON history using atomic write."""
    tmp = filename + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, filename)
    except Exception as e:
        log(f"CRITICAL: Could not save {filename}: {e}", "SYSTEM")
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e2:
            log(f"CRITICAL: Direct save also failed: {e2}", "SYSTEM")


def safe_int(value):
    """Return int(value) or None if conversion is not possible."""
    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        return None


def now_ist_string():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


# ============================================================================
# AKGSMA FETCHER
# ============================================================================

def fetch_akgsma_rates():
    """Fetch AKGSMA rates. Returns dict or None on failure."""
    url = "http://akgsma.com/index.php"

    for attempt, user_agent in enumerate(USER_AGENTS, 1):
        try:
            log(f"Attempt {attempt}/{len(USER_AGENTS)}", "AKGSMA")
            response = requests.get(url, headers={"User-Agent": user_agent}, timeout=15)
            response.raise_for_status()
            response.encoding = "utf-8"

            soup = BeautifulSoup(response.text, "html.parser")
            rates = {}

            rate_section = soup.find("ul", class_="list-block")
            if not rate_section:
                log("Rate section (ul.list-block) not found", "AKGSMA")
                continue

            items = rate_section.find_all("li")
            log(f"Found {len(items)} items in rate section", "AKGSMA")

            for item in items:
                text = item.get_text(strip=True)
                price_match = re.search(r"(\d[\d,]+)\s*$", text)
                price = price_match.group(1).replace(",", "") if price_match else None

                if "Today's Rate" in text or "Today\u2019s Rate" in text:
                    date_match = re.search(r"\((\d{2}/\d{2}/\d{4})\)", text)
                    if date_match:
                        rates["date"] = date_match.group(1)
                        log(f"Date: {rates['date']}", "AKGSMA")
                elif "22K916" in text and price:
                    rates["22K916"] = price
                    log(f"Found 22K916: Rs.{price}", "AKGSMA")
                elif "18K750" in text and price:
                    rates["18K750"] = price
                    log(f"Found 18K750: Rs.{price}", "AKGSMA")
                elif "Silver" in text and "925" not in text and price:
                    rates["Silver"] = price
                    log(f"Found Silver: Rs.{price}", "AKGSMA")

            if any(rates.get(k) for k in ["22K916", "18K750", "Silver"]):
                return rates

            log("Rate section found but no prices extracted", "AKGSMA")
        except requests.exceptions.ConnectionError:
            log(f"Connection error on attempt {attempt}", "AKGSMA")
        except requests.exceptions.Timeout:
            log(f"Timeout on attempt {attempt}", "AKGSMA")
        except Exception as e:
            log(f"Attempt {attempt} error: {str(e)[:80]}", "AKGSMA")

        time.sleep(1)

    log("All AKGSMA attempts failed", "AKGSMA")
    return None


# ============================================================================
# DERIVED KERALA OUTPUT
# ============================================================================

def derive_keralagold_rates_from_akgsma(akgsma_rates):
    """
    Derive the Kerala-style 1 pavan rate from AKGSMA 22K gram rate.
    This keeps compatibility outputs without depending on KeralaGold.
    """
    if not akgsma_rates:
        return None

    gram_rate = safe_int(akgsma_rates.get("22K916"))
    if gram_rate is None:
        return None

    akgsma_date = akgsma_rates.get("date")
    display_date = "Unknown"

    if akgsma_date:
        try:
            display_date = datetime.strptime(akgsma_date, "%d/%m/%Y").strftime("%d %B %Y").lstrip("0")
        except ValueError:
            display_date = akgsma_date

    return {
        "date": display_date,
        "date_raw": display_date,
        "today_rate": str(gram_rate * 8),
        "morning": None,
        "afternoon": None,
        "evening": None,
        "source": DERIVED_KERALA_SOURCE,
        "derived_from": "22K916 x 8",
        "gram_rate": str(gram_rate),
    }


# ============================================================================
# CHANGE TRACKING
# ============================================================================

def update_source_history(
    filename,
    current_rates,
    tracked_fields,
    source_name,
    failure_message,
    change_formatter=None,
):
    data = load_history(filename)

    if not current_rates:
        data["consecutive_failures"] = data.get("consecutive_failures", 0) + 1
        log(f"{failure_message} (failure #{data['consecutive_failures']})", source_name)
        if data["consecutive_failures"] >= 5:
            log("ALERT: 5+ consecutive failures", source_name)
        save_history(filename, data)
        return {"success": False, "changed": False}

    data["consecutive_failures"] = 0
    previous_rates = data.get("last_rates", {})

    changed = False
    changes = []

    for field in tracked_fields:
        curr = current_rates.get(field)
        prev = previous_rates.get(field)

        if not curr:
            continue

        if prev and curr != prev:
            changed = True
            if change_formatter:
                changes.append(change_formatter(field, prev, curr, False))
            else:
                changes.append(f"{field}: {prev} -> {curr}")
        elif not prev:
            changed = True
            if change_formatter:
                changes.append(change_formatter(field, prev, curr, True))
            else:
                changes.append(f"{field}: NEW {curr}")

    if changed:
        log(f"CHANGED! {', '.join(changes)}", source_name)
        data["history"].append(
            {
                "timestamp": now_ist_string(),
                "date": current_rates.get("date", "Unknown"),
                "rates": current_rates,
                "changes": changes,
            }
        )
        if len(data["history"]) > 200:
            data["history"] = data["history"][-200:]
    else:
        log("No change", source_name)

    data["last_rates"] = current_rates
    data["last_updated"] = now_ist_string()
    save_history(filename, data)
    return {"success": True, "changed": changed}


# ============================================================================
# MONITORS
# ============================================================================

def monitor_akgsma():
    log("Checking rates...", "AKGSMA")

    def format_akgsma_change(field, prev, curr, is_new):
        if is_new:
            return f"{field}: NEW ₹{curr}"
        return f"{field}: ₹{prev} -> ₹{curr}"

    return update_source_history(
        "akgsma_rates_history.json",
        fetch_akgsma_rates(),
        ["22K916", "18K750", "Silver"],
        "AKGSMA",
        "Fetch failed",
        format_akgsma_change,
    )


def monitor_keralagold_from_akgsma(akgsma_rates):
    log("Deriving pavan rate from AKGSMA 22K gram rate...", "KERALA")

    def format_kerala_change(field, prev, curr, is_new):
        label = field.replace("_", " ").title()
        if is_new:
            return f"{label}: NEW Rs.{curr}"
        return f"{label}: Rs.{prev} -> Rs.{curr}"

    return update_source_history(
        "keralagold_rates_history.json",
        derive_keralagold_rates_from_akgsma(akgsma_rates),
        ["today_rate", "morning", "afternoon", "evening"],
        "KERALA",
        "Derivation failed",
        format_kerala_change,
    )


# ============================================================================
# MAIN
# ============================================================================

def main():
    log("=" * 60, "SYSTEM")
    log("Combined Monitor Starting", "SYSTEM")
    log(f"   Python {sys.version.split()[0]} | PID {os.getpid()}", "SYSTEM")
    log("=" * 60, "SYSTEM")

    akgsma_result = monitor_akgsma()
    log("", "SYSTEM")

    akgsma_data = load_history("akgsma_rates_history.json")
    kerala_result = monitor_keralagold_from_akgsma(akgsma_data.get("last_rates", {}))

    akgsma_ok = akgsma_result["success"]
    kerala_ok = kerala_result["success"]
    rates_changed = akgsma_result["changed"] or kerala_result["changed"]

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output_file:
            output_file.write(f"rates_changed={'true' if rates_changed else 'false'}\n")

    log("=" * 60, "SYSTEM")
    if not akgsma_ok or not kerala_ok:
        no_data = [s for s, ok in [("AKGSMA", akgsma_ok), ("KERALA", kerala_ok)] if not ok]
        log("No data from: " + ", ".join(no_data), "SYSTEM")
    log("Cycle complete", "SYSTEM")
    log("=" * 60, "SYSTEM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
