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
# LOGGING (console only â€” Actions captures all print output)
# ============================================================================

def log(message, source="SYSTEM"):
    """Timestamped logger â€” console only, no file writes."""
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
        log(f"âš ï¸ Could not read {filename}: {e} â€” using fresh state", "SYSTEM")
        return {"last_rates": {}, "history": [], "last_updated": None, "consecutive_failures": 0}

def save_history(filename, data):
    """Safely save JSON history using atomic write (temp file â†’ rename)."""
    tmp = filename + ".tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, filename)
    except Exception as e:
        log(f"ðŸš¨ CRITICAL: Could not save {filename}: {e}", "SYSTEM")
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e2:
            log(f"ðŸš¨ CRITICAL: Direct save also failed: {e2}", "SYSTEM")

# ============================================================================
# DATE VALIDATION
# ============================================================================

def validate_date_freshness(date_raw, source="UNKNOWN"):
    """
    Returns True if date_raw is today or acceptably recent.
    Allows yesterday's rate before 10AM IST (sites update in the morning).
    """
    if not date_raw:
        log("âš ï¸ No date found on page â€” skipping date check", source)
        return True

    now_ist = datetime.now(IST)
    today = now_ist.date()

    try:
        page_date = datetime.strptime(date_raw.strip(), "%d %B %Y").date()
        days_diff = (today - page_date).days

        if days_diff == 0:
            log(f"âœ… Page date is today ({page_date})", source)
            return True
        elif days_diff == 1 and now_ist.hour < 10:
            log(f"â„¹ï¸ Yesterday's date ({page_date}) but before 10AM IST â€” acceptable", source)
            return True
        elif days_diff < 0:
            log(f"â„¹ï¸ Page date is in the future ({page_date}) â€” treating as fresh", source)
            return True
        else:
            log(f"âš ï¸ Stale: page shows {page_date}, today is {today} ({days_diff}d old)", source)
            return False

    except ValueError:
        try:
            cleaned = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_raw.strip())
            page_date = datetime.strptime(cleaned, "%d %B %Y").date()
            days_diff = (today - page_date).days
            if days_diff <= 1:
                return True
            log(f"âš ï¸ Stale (alt format): {page_date} is {days_diff}d old", source)
            return False
        except Exception:
            log(f"âš ï¸ Could not parse date '{date_raw}' â€” skipping date check", source)
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
    log("ðŸ” DIAGNOSTIC DUMP â€” Parser returned no results", source)
    log("=" * 55, source)

    title = soup.find('title')
    log(f"PAGE TITLE : {title.text.strip() if title else 'NOT FOUND'}", source)
    log(f"PAGE SIZE  : {len(html)} bytes", source)

    text_lines = [l.strip() for l in soup.get_text(separator='\n').splitlines() if l.strip()]

    today_lines = [l for l in text_lines if 'Today' in l or 'today' in l]
    log(f"LINES WITH 'Today' ({len(today_lines)}):", source)
    for line in today_lines[:10]:
        log(f"  â†’ {line[:120]}", source)

    all_prices = re.findall(r'Rs\.?\s*[\d,]+', soup.get_text())
    log(f"ALL PRICES FOUND ({len(all_prices)}): {all_prices[:10]}", source)

    rows = soup.find_all('tr')
    today_rows = [r for r in rows if 'Today' in r.get_text()]
    log(f"TABLE ROWS WITH 'Today' ({len(today_rows)}):", source)
    for row in today_rows[:5]:
        log(f"  â†’ {row.get_text(separator=' ', strip=True)[:120]}", source)

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
                    rates['22K916'] = text.split('â‚¹')[1].strip() if 'â‚¹' in text else None
                elif '18K750' in text:
                    rates['18K750'] = text.split('â‚¹')[1].strip() if 'â‚¹' in text else None
                elif 'Silver' in text and '925' not in text:
                    rates['Silver'] = text.split('â‚¹')[1].strip() if 'â‚¹' in text else None
                elif "Today's Rate" in text:
                    if '(' in text and ')' in text:
                        rates['date'] = text.split('(')[1].split(')')[0]

        return rates if rates else None

    except requests.exceptions.ConnectionError:
        log("âš ï¸ Site unreachable (connection error)", "AKGSMA")
        return None
    except requests.exceptions.Timeout:
        log("âš ï¸ Site timed out", "AKGSMA")
        return None
    except Exception as e:
        log(f"âš ï¸ Unexpected error: {e}", "AKGSMA")
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
                log(f"âš ï¸ Page too small ({len(response.text)} bytes) â€” likely blocked", "KERALA")
                log("----- RAW RESPONSE START -----", "KERALA")
                print(response.text[:2001])
                log("----- RAW RESPONSE END -----", "KERALA")
                continue

            log(f"âœ“ Connected (UA #{attempt}, {len(response.text)} bytes)", "KERALA")

            rates = parse_keralagold_html(response.text)

            if rates is None:
                log(f"âš ï¸ Parser returned nothing on attempt {attempt}", "KERALA")
                diagnose_page(response.text, "KERALA")
                continue

            if not validate_date_freshness(rates.get('date_raw'), "KERALA"):
                log(f"âš ï¸ Stale data on attempt {attempt} â€” retrying with next UA", "KERALA")
                time.sleep(1)
                continue

            return rates

        except requests.exceptions.Timeout:
            log(f"âš ï¸ Timeout on attempt {attempt}", "KERALA")
        except requests.exceptions.ConnectionError:
            log(f"âš ï¸ Connection error on attempt {attempt}", "KERALA")
        except Exception as e:
            log(f"âš ï¸ Attempt {attempt} error: {str(e)[:80]}", "KERALA")

        time.sleep(0.5)

    log("âŒ All attempts failed or returned stale data", "KERALA")
    return None


def parse_keralagold_html(html):
    """
    Structure-agnostic parser â€” finds rates by TEXT content not HTML tags.
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

        # â”€â”€ Strategy 1: Date from page title (most reliable) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        title = soup.find('title')
        if title:
            date_match = re.search(
                r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:' + '|'.join(MONTH_NAMES) + r')\s+\d{4})',
                title.text
            )
            if date_match:
                rates['date_raw'] = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_match.group(1))
                rates['date'] = date_match.group(1)
                log(f"ðŸ“… Date from title: {rates['date']}", "KERALA")

        # â”€â”€ Fallback date: scan all text â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if not rates['date_raw']:
            full_text = soup.get_text()
            date_match = re.search(
                r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:' + '|'.join(MONTH_NAMES) + r')\s+\d{4})',
                full_text
            )
            if date_match:
                rates['date_raw'] = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_match.group(1))
                rates['date'] = date_match.group(1)
                log(f"ðŸ“… Date from text: {rates['date']}", "KERALA")

        # â”€â”€ Strategy 2: Parse table rows by text content â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ Strategy 3: Text line scan fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        log("âš ï¸ Table strategy failed â€” trying line scan", "KERALA")
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

        log("âŒ All parse strategies exhausted", "KERALA")
        return None

    except Exception as e:
        log(f"âŒ Parse exception: {e}", "KERALA")
        return None

# ============================================================================
# AKGSMA MONITOR
# ============================================================================

def monitor_akgsma():
    log("ðŸ” Checking rates...", "AKGSMA")

    current_rates = fetch_akgsma_rates()
    data = load_history('akgsma_rates_history.json')

    if not current_rates:
        data['consecutive_failures'] = data.get('consecutive_failures', 0) + 1
        log(f"âš ï¸ Fetch failed (failure #{data['consecutive_failures']})", "AKGSMA")
        if data['consecutive_failures'] >= 5:
            log("ðŸš¨ ALERT: 5+ consecutive failures â€” site may be down!", "AKGSMA")
        save_history('akgsma_rates_history.json', data)
        return {"success": False, "changed": False}

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
            changes.append(f"{key}: â‚¹{prev} â†’ â‚¹{curr}")
        elif not prev:
            changed = True
            changes.append(f"{key}: NEW â‚¹{curr}")

    if changed:
        log(f"ðŸš¨ CHANGED! {', '.join(changes)}", "AKGSMA")
        data['history'].append({
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "date": current_rates.get('date', 'Unknown'),
            "rates": current_rates,
            "changes": changes
        })
        if len(data['history']) > 200:
            data['history'] = data['history'][-200:]
    else:
        rates_str = ', '.join([f"{k}=â‚¹{v}" for k, v in current_rates.items() if k != 'date' and v])
        log(f"âœ“ No change. {rates_str}", "AKGSMA")

    data['last_rates'] = current_rates
    data['last_updated'] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    save_history('akgsma_rates_history.json', data)
    return {"success": True, "changed": changed}

# ============================================================================
# KERALAGOLD MONITOR
# ============================================================================

def monitor_keralagold():
    log("ðŸ” Checking rates...", "KERALA")

    current_rates = fetch_keralagold_rates()
    data = load_history('keralagold_rates_history.json')

    if not current_rates:
        data['consecutive_failures'] = data.get('consecutive_failures', 0) + 1
        log(f"âš ï¸ Fetch failed (failure #{data['consecutive_failures']})", "KERALA")
        if data['consecutive_failures'] >= 5:
            log("ðŸš¨ ALERT: 5+ consecutive failures â€” site may be down or parser broken!", "KERALA")
        save_history('keralagold_rates_history.json', data)
        return {"success": False, "changed": False}

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
            changes.append(f"{field.replace('_', ' ').title()}: Rs.{prev} â†’ Rs.{curr}")
        elif not prev:
            changed = True
            changes.append(f"{field.replace('_', ' ').title()}: NEW Rs.{curr}")

    if changed:
        log(f"ðŸš¨ CHANGED! {', '.join(changes)}", "KERALA")
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
        log(f"âœ“ No change. {rates_str}", "KERALA")

    data['last_rates'] = current_rates
    data['last_updated'] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    save_history('keralagold_rates_history.json', data)
    return {"success": True, "changed": changed}

# ============================================================================
# MAIN
# ============================================================================

def main():
    log("=" * 60, "SYSTEM")
    log("🚀 Combined Monitor Starting", "SYSTEM")
    log(f"   Python {sys.version.split()[0]} | PID {os.getpid()}", "SYSTEM")
    log("=" * 60, "SYSTEM")

    akgsma_result = monitor_akgsma()
    log("", "SYSTEM")
    kerala_result = monitor_keralagold()

    akgsma_ok = akgsma_result["success"]
    kerala_ok = kerala_result["success"]
    rates_changed = akgsma_result["changed"] or kerala_result["changed"]

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output_file:
            output_file.write(f"rates_changed={'true' if rates_changed else 'false'}\n")

    log("=" * 60, "SYSTEM")
    if akgsma_ok and kerala_ok:
        log("✅ Cycle complete", "SYSTEM")
        exit_code = 0
    else:
        failed_sources = []
        if not akgsma_ok:
            failed_sources.append("AKGSMA")
        if not kerala_ok:
            failed_sources.append("KERALA")
        log(f"❌ Cycle completed with failures in: {', '.join(failed_sources)}", "SYSTEM")
        exit_code = 1
    log("=" * 60, "SYSTEM")
    return exit_code

if __name__ == "__main__":
    sys.exit(main())

