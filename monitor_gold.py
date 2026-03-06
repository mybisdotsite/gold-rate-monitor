import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
]

# ============================================================================
# LOGGING (console only — Actions captures all print output)
# ============================================================================

def log(message, source="SYSTEM"):
    """Timestamped logger — console only, no file writes."""
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"[{timestamp}] [{source}] {message}")

# ============================================================================
# HISTORY HELPERS
# ============================================================================

def load_history(filename):
    """Safely load JSON history. Returns clean default on any error."""
    if not os.path.exists(filename):
        return {"last_rates": {}, "history": [], "last_updated": None, "consecutive_failures": 0}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data.setdefault("last_rates", {})
        data.setdefault("history", [])
        data.setdefault("last_updated", None)
        data.setdefault("consecutive_failures", 0)
        return data
    except Exception as e:
        log(f"⚠️ Could not read {filename}: {e} — using fresh state", "SYSTEM")
        return {"last_rates": {}, "history": [], "last_updated": None, "consecutive_failures": 0}

def save_history(filename, data):
    """Safely save JSON history using atomic write (temp file → rename)."""
    tmp = filename + ".tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, filename)
    except Exception as e:
        log(f"🚨 CRITICAL: Could not save {filename}: {e}", "SYSTEM")
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e2:
            log(f"🚨 CRITICAL: Direct save also failed: {e2}", "SYSTEM")

# ============================================================================
# DATE VALIDATION
# ============================================================================

def validate_date_freshness(date_raw, source="UNKNOWN"):
    """
    Returns True if date_raw is today or acceptably recent.
    Allows yesterday's rate before 10AM IST (sites update in the morning).
    """
    if not date_raw:
        log("⚠️ No date found on page — skipping date check", source)
        return True

    now_ist = datetime.now(IST)
    today = now_ist.date()

    try:
        page_date = datetime.strptime(date_raw.strip(), "%d %B %Y").date()
        days_diff = (today - page_date).days

        if days_diff == 0:
            log(f"✅ Page date is today ({page_date})", source)
            return True
        elif days_diff == 1 and now_ist.hour < 10:
            log(f"ℹ️ Yesterday's date ({page_date}) but before 10AM IST — acceptable", source)
            return True
        elif days_diff < 0:
            log(f"ℹ️ Page date is in the future ({page_date}) — treating as fresh", source)
            return True
        else:
            log(f"⚠️ Stale: page shows {page_date}, today is {today} ({days_diff}d old)", source)
            return False

    except ValueError:
        try:
            cleaned = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_raw.strip())
            page_date = datetime.strptime(cleaned, "%d %B %Y").date()
            days_diff = (today - page_date).days
            if days_diff <= 1:
                return True
            log(f"⚠️ Stale (alt format): {page_date} is {days_diff}d old", source)
            return False
        except Exception:
            log(f"⚠️ Could not parse date '{date_raw}' — skipping date check", source)
            return True

# ============================================================================
# DIAGNOSTIC DUMP (auto-runs when parser fails)
# ============================================================================

def diagnose_page(html, source="UNKNOWN"):
    """
    Dumps a clean diagnostic when parser returns None.
    Instantly shows what changed on the site so you can fix in seconds.
    """
    soup = BeautifulSoup(html, 'html.parser')
    log("=" * 55, source)
    log("🔍 DIAGNOSTIC DUMP — Parser returned no results", source)
    log("=" * 55, source)

    title = soup.find('title')
    log(f"PAGE TITLE : {title.text.strip() if title else 'NOT FOUND'}", source)
    log(f"PAGE SIZE  : {len(html)} bytes", source)

    text_lines = [l.strip() for l in soup.get_text(separator='\n').splitlines() if l.strip()]

    today_lines = [l for l in text_lines if 'Today' in l or 'today' in l]
    log(f"LINES WITH 'Today' ({len(today_lines)}):", source)
    for line in today_lines[:10]:
        log(f"  → {line[:120]}", source)

    all_prices = re.findall(r'Rs\.?\s*[\d,]+', soup.get_text())
    log(f"ALL PRICES FOUND ({len(all_prices)}): {all_prices[:10]}", source)

    rows = soup.find_all('tr')
    today_rows = [r for r in rows if 'Today' in r.get_text()]
    log(f"TABLE ROWS WITH 'Today' ({len(today_rows)}):", source)
    for row in today_rows[:5]:
        log(f"  → {row.get_text(separator=' ', strip=True)[:120]}", source)

    log("=" * 55, source)

# ============================================================================
# AKGSMA FETCHER
# ============================================================================

def fetch_akgsma_rates():
    """Fetch AKGSMA rates. Returns dict or None on failure."""
    url = "http://akgsma.com/index.php"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        rates = {}
        rate_section = soup.find('ul', class_='list-block')

        if rate_section:
            items = rate_section.find_all('li')
            for item in items:
                text = item.get_text(strip=True)
                if '22K916' in text:
                    rates['22K916'] = text.split('₹')[1].strip() if '₹' in text else None
                elif '18K750' in text:
                    rates['18K750'] = text.split('₹')[1].strip() if '₹' in text else None
                elif 'Silver' in text and '925' not in text:
                    rates['Silver'] = text.split('₹')[1].strip() if '₹' in text else None
                elif "Today's Rate" in text:
                    if '(' in text and ')' in text:
                        rates['date'] = text.split('(')[1].split(')')[0]

        return rates if rates else None

    except requests.exceptions.ConnectionError:
        log("⚠️ Site unreachable (connection error)", "AKGSMA")
        return None
    except requests.exceptions.Timeout:
        log("⚠️ Site timed out", "AKGSMA")
        return None
    except Exception as e:
        log(f"⚠️ Unexpected error: {e}", "AKGSMA")
        return None

# ============================================================================
# KERALAGOLD FETCHER
# ============================================================================

def fetch_keralagold_rates():
    """
    Fetch KeralaGold rates.
    - Cache-busting query param on every request
    - Rotates User-Agents
    - Validates date freshness on each attempt before accepting
    - Auto-diagnoses if all attempts fail
    Returns dict or None on failure.
    """
    base_url = "https://www.keralagold.com/daily-gold-prices.htm"

    for attempt, user_agent in enumerate(USER_AGENTS, 1):
        try:
            cache_bust = int(time.time() * 1000)
            url = f"{base_url}?_={cache_bust}"

            headers = {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9,ml;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Referer": "https://www.google.com/search?q=kerala+gold+rate+today",
                "Upgrade-Insecure-Requests": "1",
            }

            log(f"Attempt {attempt}/{len(USER_AGENTS)}", "KERALA")
            time.sleep(random.uniform(0.3, 0.8))

            session = requests.Session()
            response = session.get(url, headers=headers, timeout=20)

            if response.status_code != 200:
                log(f"HTTP {response.status_code} on attempt {attempt}", "KERALA")
                continue

            if len(response.text) < 3000:
                log(f"⚠️ Page too small ({len(response.text)} bytes) — likely blocked", "KERALA")
                log("----- RAW RESPONSE START -----", "KERALA")
                print(response.text[:2001])
                log("----- RAW RESPONSE END -----", "KERALA")
                continue

            log(f"✓ Connected (UA #{attempt}, {len(response.text)} bytes)", "KERALA")

            rates = parse_keralagold_html(response.text)

            if rates is None:
                log(f"⚠️ Parser returned nothing on attempt {attempt}", "KERALA")
                diagnose_page(response.text, "KERALA")
                continue

            if not validate_date_freshness(rates.get('date_raw'), "KERALA"):
                log(f"⚠️ Stale data on attempt {attempt} — retrying with next UA", "KERALA")
                time.sleep(1)
                continue

            return rates

        except requests.exceptions.Timeout:
            log(f"⚠️ Timeout on attempt {attempt}", "KERALA")
        except requests.exceptions.ConnectionError:
            log(f"⚠️ Connection error on attempt {attempt}", "KERALA")
        except Exception as e:
            log(f"⚠️ Attempt {attempt} error: {str(e)[:80]}", "KERALA")

        time.sleep(0.5)

    log("❌ All attempts failed or returned stale data", "KERALA")
    return None


def parse_keralagold_html(html):
    """
    Structure-agnostic parser — finds rates by TEXT content not HTML tags.
    Works even if site redesigns layout, changes class names, or adds new tags.
    Falls back through multiple strategies before giving up.
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')
        rates = {
            'date': None,
            'date_raw': None,
            'today_rate': None,
            'morning': None,
            'afternoon': None,
            'evening': None
        }

        # ── Strategy 1: Date from page title (most reliable) ──────────
        title = soup.find('title')
        if title:
            date_match = re.search(
                r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:' + '|'.join(MONTH_NAMES) + r')\s+\d{4})',
                title.text
            )
            if date_match:
                rates['date_raw'] = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_match.group(1))
                rates['date'] = date_match.group(1)
                log(f"📅 Date from title: {rates['date']}", "KERALA")

        # ── Fallback date: scan all text ───────────────────────────────
        if not rates['date_raw']:
            full_text = soup.get_text()
            date_match = re.search(
                r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:' + '|'.join(MONTH_NAMES) + r')\s+\d{4})',
                full_text
            )
            if date_match:
                rates['date_raw'] = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_match.group(1))
                rates['date'] = date_match.group(1)
                log(f"📅 Date from text: {rates['date']}", "KERALA")

        # ── Strategy 2: Parse table rows by text content ───────────────
        for row in soup.find_all('tr'):
            row_text = row.get_text(separator=' ', strip=True)

            if 'Today' not in row_text:
                continue

            price_match = re.search(r'Rs\.?\s*([\d,]+)', row_text)
            if not price_match:
                continue

            price = price_match.group(1).replace(',', '')
            row_lower = row_text.lower()

            if 'morning' in row_lower:
                rates['morning'] = price
                log(f"Found Morning: Rs.{price}", "KERALA")
            elif 'afternoon' in row_lower or 'noon' in row_lower:
                rates['afternoon'] = price
                log(f"Found Afternoon: Rs.{price}", "KERALA")
            elif 'evening' in row_lower or 'night' in row_lower:
                rates['evening'] = price
                log(f"Found Evening: Rs.{price}", "KERALA")
            else:
                rates['today_rate'] = price
                log(f"Found Today rate: Rs.{price}", "KERALA")

        if any(rates[k] for k in ['today_rate', 'morning', 'afternoon', 'evening']):
            return rates

        # ── Strategy 3: Text line scan fallback ───────────────────────
        log("⚠️ Table strategy failed — trying line scan", "KERALA")
        text_lines = [l.strip() for l in soup.get_text(separator='\n').splitlines() if l.strip()]

        found_today_idx = None
        for i, line in enumerate(text_lines):
            if 'Today' in line:
                found_today_idx = i
                break

        if found_today_idx is not None:
            window = text_lines[found_today_idx:found_today_idx + 8]
            for line in window:
                price_match = re.search(r'Rs\.?\s*([\d,]+)', line)
                if price_match:
                    price = price_match.group(1).replace(',', '')
                    rates['today_rate'] = price
                    log(f"Fallback found rate: Rs.{price}", "KERALA")
                    return rates

        log("❌ All parse strategies exhausted", "KERALA")
        return None

    except Exception as e:
        log(f"❌ Parse exception: {e}", "KERALA")
        return None

# ============================================================================
# AKGSMA MONITOR
# ============================================================================

def monitor_akgsma():
    log("🔍 Checking rates...", "AKGSMA")

    current_rates = fetch_akgsma_rates()
    data = load_history('akgsma_rates_history.json')

    if not current_rates:
        data['consecutive_failures'] = data.get('consecutive_failures', 0) + 1
        log(f"⚠️ Fetch failed (failure #{data['consecutive_failures']})", "AKGSMA")
        if data['consecutive_failures'] >= 5:
            log("🚨 ALERT: 5+ consecutive failures — site may be down!", "AKGSMA")
        save_history('akgsma_rates_history.json', data)
        return

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
        log(f"🚨 CHANGED! {', '.join(changes)}", "AKGSMA")
        data['history'].append({
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "date": current_rates.get('date', 'Unknown'),
            "rates": current_rates,
            "changes": changes
        })
        if len(data['history']) > 200:
            data['history'] = data['history'][-200:]
    else:
        rates_str = ', '.join([f"{k}=₹{v}" for k, v in current_rates.items() if k != 'date' and v])
        log(f"✓ No change. {rates_str}", "AKGSMA")

    data['last_rates'] = current_rates
    data['last_updated'] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    save_history('akgsma_rates_history.json', data)

# ============================================================================
# KERALAGOLD MONITOR
# ============================================================================

def monitor_keralagold():
    log("🔍 Checking rates...", "KERALA")

    current_rates = fetch_keralagold_rates()
    data = load_history('keralagold_rates_history.json')

    if not current_rates:
        data['consecutive_failures'] = data.get('consecutive_failures', 0) + 1
        log(f"⚠️ Fetch failed (failure #{data['consecutive_failures']})", "KERALA")
        if data['consecutive_failures'] >= 5:
            log("🚨 ALERT: 5+ consecutive failures — site may be down or parser broken!", "KERALA")
        save_history('keralagold_rates_history.json', data)
        return

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
        log(f"🚨 CHANGED! {', '.join(changes)}", "KERALA")
        data['history'].append({
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "date": current_rates.get('date', 'Unknown'),
            "rates": current_rates,
            "changes": changes
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

    data['last_rates'] = current_rates
    data['last_updated'] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    save_history('keralagold_rates_history.json', data)

# ============================================================================
# MAIN
# ============================================================================

def main():
    log("=" * 60, "SYSTEM")
    log("🚀 Combined Monitor Starting", "SYSTEM")
    log(f"   Python {sys.version.split()[0]} | PID {os.getpid()}", "SYSTEM")
    log("=" * 60, "SYSTEM")

    monitor_akgsma()
    log("", "SYSTEM")
    monitor_keralagold()

    log("=" * 60, "SYSTEM")
    log("✅ Cycle complete", "SYSTEM")
    log("=" * 60, "SYSTEM")

if __name__ == "__main__":
    main()
