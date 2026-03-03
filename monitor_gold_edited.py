"""
monitor_gold.py — Production Gold Rate Monitor
Monitors AKGSMA and KeralaGold websites for rate changes.
Saves history to JSON files consumed by dependent services.

Key guarantees:
- Atomic JSON saves (never corrupts history files)
- Accepts best-available data even when CDN serves stale pages
- Auto-diagnoses parser failures in GitHub Actions logs
- Tracks consecutive failures per source
- Structure-agnostic parser (survives site redesigns)
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import os
import pytz
import re
import time
import random
import sys

# ============================================================================
# CONSTANTS
# ============================================================================

IST = pytz.timezone('Asia/Kolkata')

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
]

# ============================================================================
# LOGGING
# ============================================================================

def log(message, source="SYSTEM"):
    """Timestamped logger — writes to console and monitoring_log.txt."""
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    line = f"[{timestamp}] [{source}] {message}"
    print(line)
    try:
        with open('monitoring_log.txt', 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[WARN] Could not write to log file: {e}")

# ============================================================================
# HISTORY HELPERS
# ============================================================================

def load_history(filename):
    """
    Safely load JSON history file.
    Returns clean default structure on any error or missing file.
    Handles old-format files missing newer keys gracefully.
    """
    default = {
        "last_rates": {},
        "history": [],
        "last_updated": None,
        "consecutive_failures": 0,
    }

    if not os.path.exists(filename):
        return default

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Backfill any missing keys introduced in newer versions
        for key, val in default.items():
            data.setdefault(key, val)
        return data

    except json.JSONDecodeError as e:
        log(f"⚠️ Corrupt JSON in {filename}: {e} — resetting to clean state", "SYSTEM")
        return default
    except Exception as e:
        log(f"⚠️ Could not read {filename}: {e} — using clean state", "SYSTEM")
        return default


def save_history(filename, data):
    """
    Atomic JSON save using temp-file + rename.
    History files are never left corrupt even if process is killed mid-write.
    """
    tmp = filename + ".tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, filename)  # Atomic on POSIX and Windows
    except Exception as e:
        log(f"🚨 CRITICAL: Atomic save failed for {filename}: {e}", "SYSTEM")
        # Last resort: direct write
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            log(f"⚠️ Direct-write fallback succeeded for {filename}", "SYSTEM")
        except Exception as e2:
            log(f"🚨 CRITICAL: All save attempts failed for {filename}: {e2}", "SYSTEM")

# ============================================================================
# DATE UTILITIES
# ============================================================================

def parse_date_string(date_raw):
    """
    Parse date strings like '2 March 2026' or '2nd March 2026'.
    Returns a date object or None if unparseable.
    """
    if not date_raw:
        return None
    try:
        cleaned = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_raw.strip())
        return datetime.strptime(cleaned, "%d %B %Y").date()
    except ValueError:
        return None


def validate_and_compare_freshness(fetched_rates, stored_rates, source="UNKNOWN"):
    """
    Decides whether fetched data should be accepted and saved.

    Decision order:
    1. No date on fetched page           → accept (can't validate, don't block)
    2. No stored data yet (first run)    → accept always
    3. Fetched date > stored date        → accept (genuine new data)
    4. Fetched date == stored date       → accept (may have new time-period rates)
    5. Fetched date < stored date        → REJECT (CDN regression — older than stored)

    Returns: (should_accept: bool, reason: str)
    """
    fetched_date = parse_date_string(fetched_rates.get('date_raw'))
    stored_date  = parse_date_string(
        stored_rates.get('date_raw') or stored_rates.get('date')
    )

    if fetched_date is None:
        log("⚠️ No date on fetched page — accepting without date validation", source)
        return True, "no_date_on_page"

    if stored_date is None:
        log(f"ℹ️ No stored data yet — accepting fetched date {fetched_date}", source)
        return True, "first_run"

    if fetched_date > stored_date:
        log(f"✅ Fetched ({fetched_date}) newer than stored ({stored_date}) — accepting", source)
        return True, "newer_than_stored"

    if fetched_date == stored_date:
        log(f"ℹ️ Same date as stored ({fetched_date}) — accepting", source)
        return True, "same_date_as_stored"

    # fetched_date < stored_date
    log(
        f"🚨 Fetched ({fetched_date}) is OLDER than stored ({stored_date}) "
        f"— CDN regression, rejecting this attempt",
        source
    )
    return False, "older_than_stored"

# ============================================================================
# DIAGNOSTIC DUMP
# ============================================================================

def diagnose_page(html, source="UNKNOWN"):
    """
    Structured diagnostic dump when the parser returns None.
    Visible in GitHub Actions logs — shows exactly what changed on the site
    so the parser can be fixed in minutes.
    """
    soup = BeautifulSoup(html, 'html.parser')

    log("=" * 55, source)
    log("🔍 PARSER DIAGNOSTIC DUMP", source)
    log("=" * 55, source)

    title = soup.find('title')
    log(f"PAGE TITLE : {title.text.strip() if title else 'NOT FOUND'}", source)
    log(f"PAGE SIZE  : {len(html)} bytes", source)

    text_lines = [l.strip() for l in soup.get_text(separator='\n').splitlines() if l.strip()]

    today_lines = [l for l in text_lines if 'Today' in l]
    log(f"LINES WITH 'Today' ({len(today_lines)}):", source)
    for line in today_lines[:10]:
        log(f"  → {line[:120]}", source)

    all_prices = re.findall(r'Rs\.?\s*[\d,]+', soup.get_text())
    log(f"ALL PRICES FOUND: {all_prices[:10]}", source)

    rows = soup.find_all('tr')
    today_rows = [r for r in rows if 'Today' in r.get_text()]
    log(f"TABLE ROWS WITH 'Today' ({len(today_rows)}):", source)
    for row in today_rows[:5]:
        log(f"  → {row.get_text(separator=' ', strip=True)[:120]}", source)

    log("=" * 55, source)

# ============================================================================
# AKGSMA — FETCH
# ============================================================================

def fetch_akgsma_rates():
    """
    Fetch AKGSMA gold rates.
    Returns dict with keys: 22K916, 18K750, Silver, date
    Returns None on any failure.
    """
    url = "http://akgsma.com/index.php"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        rates = {}
        rate_section = soup.find('ul', class_='list-block')

        if not rate_section:
            log("⚠️ Rate section (ul.list-block) not found — site may have changed", "AKGSMA")
            return None

        for item in rate_section.find_all('li'):
            text = item.get_text(strip=True)
            if '22K916' in text:
                rates['22K916'] = text.split('₹')[1].strip() if '₹' in text else None
            elif '18K750' in text:
                rates['18K750'] = text.split('₹')[1].strip() if '₹' in text else None
            elif 'Silver' in text and '925' not in text:
                rates['Silver'] = text.split('₹')[1].strip() if '₹' in text else None
            elif "Today's Rate" in text and '(' in text and ')' in text:
                rates['date'] = text.split('(')[1].split(')')[0]

        # Only return if we got at least one actual rate value
        has_rate = any(rates.get(k) for k in ['22K916', '18K750', 'Silver'])
        if not has_rate:
            log("⚠️ Page loaded but no rates found — site structure may have changed", "AKGSMA")
            return None

        return rates

    except requests.exceptions.ConnectionError:
        log("⚠️ Connection error — site unreachable or IP blocked", "AKGSMA")
        return None
    except requests.exceptions.Timeout:
        log("⚠️ Request timed out", "AKGSMA")
        return None
    except requests.exceptions.HTTPError as e:
        log(f"⚠️ HTTP error: {e}", "AKGSMA")
        return None
    except Exception as e:
        log(f"⚠️ Unexpected error: {e}", "AKGSMA")
        return None

# ============================================================================
# KERALAGOLD — PARSE
# ============================================================================

def parse_keralagold_html(html):
    """
    Structure-agnostic parser — finds rates by TEXT CONTENT, not HTML tags.
    Survives site redesigns as long as 'Today', 'Rs.' and month names remain.

    Strategy 1 — Table row scan:
        Finds every <tr> containing the word 'Today' and extracts its price.
        Determines time period (Morning / Afternoon / Evening) from row text.

    Strategy 2 — Plain-text line scan:
        Falls back to scanning visible text lines for 'Today' then nearby 'Rs.'
        Works even if the site switches from tables to divs or any other layout.

    Returns dict or None if no rates found (triggers diagnostic dump in caller).
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')

        rates = {
            'date':       None,
            'date_raw':   None,
            'today_rate': None,
            'morning':    None,
            'afternoon':  None,
            'evening':    None,
        }

        date_pattern = (
            r'(\d{1,2}(?:st|nd|rd|th)?\s+'
            r'(?:' + '|'.join(MONTH_NAMES) + r')'
            r'\s+\d{4})'
        )

        # ── Date: page <title> is most reliable ───────────────────────
        title = soup.find('title')
        if title:
            m = re.search(date_pattern, title.text)
            if m:
                rates['date']     = m.group(1)
                rates['date_raw'] = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', m.group(1))
                log(f"📅 Date from title: {rates['date']}", "KERALA")

        # ── Date: fallback to body text ────────────────────────────────
        if not rates['date_raw']:
            m = re.search(date_pattern, soup.get_text())
            if m:
                rates['date']     = m.group(1)
                rates['date_raw'] = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', m.group(1))
                log(f"📅 Date from body: {rates['date']}", "KERALA")

        rate_keys = ['today_rate', 'morning', 'afternoon', 'evening']

        # ── Strategy 1: Table row scan ─────────────────────────────────
        for row in soup.find_all('tr'):
            row_text = row.get_text(separator=' ', strip=True)

            if 'Today' not in row_text:
                continue

            price_match = re.search(r'Rs\.?\s*([\d,]+)', row_text)
            if not price_match:
                continue

            price     = price_match.group(1).replace(',', '')
            row_lower = row_text.lower()

            if 'morning' in row_lower:
                rates['morning']    = price
                log(f"Found Morning: Rs.{price}", "KERALA")
            elif 'afternoon' in row_lower or 'noon' in row_lower:
                rates['afternoon']  = price
                log(f"Found Afternoon: Rs.{price}", "KERALA")
            elif 'evening' in row_lower or 'night' in row_lower:
                rates['evening']    = price
                log(f"Found Evening: Rs.{price}", "KERALA")
            else:
                rates['today_rate'] = price
                log(f"Found Today rate: Rs.{price}", "KERALA")

        if any(rates[k] for k in rate_keys):
            return rates

        # ── Strategy 2: Plain-text line scan ──────────────────────────
        log("⚠️ Table scan found nothing — falling back to line scan", "KERALA")

        text_lines = [
            l.strip()
            for l in soup.get_text(separator='\n').splitlines()
            if l.strip()
        ]

        for i, line in enumerate(text_lines):
            if 'Today' not in line:
                continue

            for nearby in text_lines[i:i + 8]:
                price_match = re.search(r'Rs\.?\s*([\d,]+)', nearby)
                if not price_match:
                    continue

                price        = price_match.group(1).replace(',', '')
                nearby_lower = nearby.lower()

                if 'morning' in nearby_lower:
                    rates['morning']    = price
                elif 'afternoon' in nearby_lower or 'noon' in nearby_lower:
                    rates['afternoon']  = price
                elif 'evening' in nearby_lower or 'night' in nearby_lower:
                    rates['evening']    = price
                else:
                    rates['today_rate'] = price

                log(f"Line-scan found rate: Rs.{price}", "KERALA")

            if any(rates[k] for k in rate_keys):
                return rates

        log("❌ All parse strategies exhausted — no rates found", "KERALA")
        return None

    except Exception as e:
        log(f"❌ Parser exception: {e}", "KERALA")
        return None

# ============================================================================
# KERALAGOLD — FETCH
# ============================================================================

def fetch_keralagold_rates(stored_rates=None):
    """
    Fetch KeralaGold rates.

    Per-attempt:
    - Cache-busting ?_=<timestamp> param forces fresh response
    - Rotates through 4 User-Agents
    - Rejects pages < 3000 bytes (blocked / error pages)
    - Validates freshness vs stored data (not just vs today)

    After all attempts:
    - If any attempt was parsed successfully but rejected only on freshness,
      returns that as last-resort (better than leaving services with no update).
    - If nothing could be parsed at all, returns None.
    """
    base_url     = "https://www.keralagold.com/daily-gold-prices.htm"
    stored_rates = stored_rates or {}

    # Holds last successfully parsed result even if freshness check rejected it
    last_parsed_result = None

    for attempt, user_agent in enumerate(USER_AGENTS, 1):
        try:
            cache_bust = int(time.time() * 1000)
            url = f"{base_url}?_={cache_bust}"

            headers = {
                "User-Agent":                user_agent,
                "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language":           "en-IN,en;q=0.9,ml;q=0.8",
                "Accept-Encoding":           "gzip, deflate, br",
                "Connection":                "keep-alive",
                "Cache-Control":             "no-cache, no-store, must-revalidate",
                "Pragma":                    "no-cache",
                "Expires":                   "0",
                "Referer":                   "https://www.google.com/search?q=kerala+gold+rate+today",
                "Upgrade-Insecure-Requests": "1",
            }

            log(f"Attempt {attempt}/{len(USER_AGENTS)}", "KERALA")
            time.sleep(random.uniform(0.3, 0.8))

            session  = requests.Session()
            response = session.get(url, headers=headers, timeout=20)

            if response.status_code != 200:
                log(f"HTTP {response.status_code} on attempt {attempt}", "KERALA")
                continue

            if len(response.text) < 3000:
                log(
                    f"⚠️ Page too small ({len(response.text)} bytes) "
                    f"— likely blocked or error page",
                    "KERALA"
                )
                continue

            log(f"✓ Connected (UA #{attempt}, {len(response.text)} bytes)", "KERALA")

            rates = parse_keralagold_html(response.text)

            if rates is None:
                log(f"⚠️ Parser returned nothing on attempt {attempt}", "KERALA")
                diagnose_page(response.text, "KERALA")
                continue

            # Save as last-resort candidate regardless of freshness outcome
            last_parsed_result = rates

            should_accept, reason = validate_and_compare_freshness(
                rates, stored_rates, "KERALA"
            )

            if should_accept:
                log(f"✅ Accepted (reason: {reason})", "KERALA")
                return rates

            log(
                f"⚠️ Rejected (reason: {reason}) on attempt {attempt} "
                f"— trying next UA",
                "KERALA"
            )
            time.sleep(1)

        except requests.exceptions.Timeout:
            log(f"⚠️ Timeout on attempt {attempt}", "KERALA")
        except requests.exceptions.ConnectionError:
            log(f"⚠️ Connection error on attempt {attempt}", "KERALA")
        except Exception as e:
            log(f"⚠️ Attempt {attempt} unexpected error: {str(e)[:80]}", "KERALA")

        time.sleep(0.5)

    # ── All attempts exhausted ─────────────────────────────────────────────
    if last_parsed_result is not None:
        log(
            "⚠️ All UAs exhausted — returning last parsed result as best available "
            "(prevents dependent services from receiving no update)",
            "KERALA"
        )
        return last_parsed_result

    log("❌ All attempts failed — no usable data retrieved", "KERALA")
    return None

# ============================================================================
# AKGSMA — MONITOR
# ============================================================================

def monitor_akgsma():
    log("🔍 Checking rates...", "AKGSMA")

    current_rates = fetch_akgsma_rates()
    data = load_history('akgsma_rates_history.json')

    # ── Fetch failed ──────────────────────────────────────────────────────
    if not current_rates:
        data['consecutive_failures'] = data.get('consecutive_failures', 0) + 1
        failures = data['consecutive_failures']
        log(f"⚠️ Fetch failed (consecutive failure #{failures})", "AKGSMA")
        if failures >= 5:
            log(
                f"🚨 ALERT: {failures} consecutive failures — "
                f"site may be permanently down or IP is blocked",
                "AKGSMA"
            )
        save_history('akgsma_rates_history.json', data)
        return

    # ── Fetch succeeded ───────────────────────────────────────────────────
    data['consecutive_failures'] = 0
    previous_rates = data.get('last_rates', {})

    changed = False
    changes = []

    for key in ['22K916', '18K750', 'Silver']:
        curr = current_rates.get(key)
        prev = previous_rates.get(key)

        if not curr:
            continue

        if prev and curr != prev:
            changed = True
            changes.append(f"{key}: ₹{prev} → ₹{curr}")
        elif not prev:
            changed = True
            changes.append(f"{key}: NEW ₹{curr}")

    if changed:
        log(f"🚨 RATE CHANGED! {', '.join(changes)}", "AKGSMA")
        data['history'].append({
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "date":      current_rates.get('date', 'Unknown'),
            "rates":     current_rates,
            "changes":   changes,
        })
        if len(data['history']) > 200:
            data['history'] = data['history'][-200:]
    else:
        rates_str = ', '.join([
            f"{k}=₹{v}"
            for k, v in current_rates.items()
            if k != 'date' and v
        ])
        log(f"✓ No change. {rates_str}", "AKGSMA")

    data['last_rates']   = current_rates
    data['last_updated'] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    save_history('akgsma_rates_history.json', data)

# ============================================================================
# KERALAGOLD — MONITOR
# ============================================================================

def monitor_keralagold():
    log("🔍 Checking rates...", "KERALA")

    # Load history FIRST — pass stored rates to fetcher for freshness comparison
    data = load_history('keralagold_rates_history.json')
    current_rates = fetch_keralagold_rates(stored_rates=data.get('last_rates', {}))

    # ── Fetch failed ──────────────────────────────────────────────────────
    if not current_rates:
        data['consecutive_failures'] = data.get('consecutive_failures', 0) + 1
        failures = data['consecutive_failures']
        log(f"⚠️ Fetch failed (consecutive failure #{failures})", "KERALA")
        if failures >= 5:
            log(
                f"🚨 ALERT: {failures} consecutive failures — "
                f"site may be down or parser is broken (check diagnostic dump above)",
                "KERALA"
            )
        save_history('keralagold_rates_history.json', data)
        return

    # ── Fetch succeeded ───────────────────────────────────────────────────
    data['consecutive_failures'] = 0
    previous_rates = data.get('last_rates', {})

    changed = False
    changes = []

    rate_fields = ['today_rate', 'morning', 'afternoon', 'evening']
    for field in rate_fields:
        curr = current_rates.get(field)
        prev = previous_rates.get(field)

        if not curr:
            continue

        if prev and curr != prev:
            changed = True
            changes.append(f"{field.replace('_', ' ').title()}: Rs.{prev} → Rs.{curr}")
        elif not prev:
            changed = True
            changes.append(f"{field.replace('_', ' ').title()}: NEW Rs.{curr}")

    if changed:
        log(f"🚨 RATE CHANGED! {', '.join(changes)}", "KERALA")
        data['history'].append({
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "date":      current_rates.get('date', 'Unknown'),
            "rates":     current_rates,
            "changes":   changes,
        })
        if len(data['history']) > 200:
            data['history'] = data['history'][-200:]
    else:
        rates_str = ', '.join([
            f"{k.replace('_', ' ').title()}=Rs.{v}"
            for k, v in current_rates.items()
            if k not in ('date', 'date_raw') and v
        ])
        log(f"✓ No change. {rates_str}", "KERALA")

    data['last_rates']   = current_rates
    data['last_updated'] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    save_history('keralagold_rates_history.json', data)

# ============================================================================
# MAIN
# ============================================================================

def main():
    log("=" * 60, "SYSTEM")
    log("🚀 Gold Rate Monitor Starting", "SYSTEM")
    log(f"   Python {sys.version.split()[0]} | PID {os.getpid()}", "SYSTEM")
    log("=" * 60, "SYSTEM")

    monitor_akgsma()
    log("", "SYSTEM")
    monitor_keralagold()

    log("=" * 60, "SYSTEM")
    log("✅ Cycle complete", "SYSTEM")
    log("=" * 60, "SYSTEM")
    log("", "SYSTEM")


if __name__ == "__main__":
    main()