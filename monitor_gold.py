import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import os
import pytz
import re
import time
import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

def log_message(message, source="SYSTEM"):
    ist = pytz.timezone('Asia/Kolkata')
    timestamp = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")
    log_line = f"[{timestamp}] [{source}] {message}\n"
    print(log_line.strip())
    with open('monitoring_log.txt', 'a') as f:
        f.write(log_line)

def load_history(filename):
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except:
            return {"last_rates": {}, "history": []}
    return {"last_rates": {}, "history": []}

def save_history(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

def get_today_string():
    """Get today's date in IST as string for comparison"""
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist).strftime("%Y-%m-%d")

# ============================================================================
# AKGSMA FETCHER (unchanged)
# ============================================================================
def fetch_akgsma_rates():
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
                elif 'Today\'s Rate' in text:
                    if '(' in text and ')' in text:
                        rates['date'] = text.split('(')[1].split(')')[0]

        return rates if rates else None
    except Exception as e:
        log_message(f"Error: {e}", "AKGSMA")
        return None

# ============================================================================
# KERALAGOLD FETCHER (FIXED - cache busting + date validation)
# ============================================================================
def fetch_keralagold_rates():
    """Fetch KeralaGold rates with cache-busting"""
    base_url = "https://www.keralagold.com/daily-gold-prices.htm"

    for attempt, user_agent in enumerate(USER_AGENTS, 1):
        try:
            session = requests.Session()

            # ✅ FIX 1: Cache-busting via unique timestamp query param
            cache_bust = int(time.time() * 1000)
            url = f"{base_url}?_={cache_bust}"

            headers = {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9,ml;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                # ✅ FIX 2: Stronger cache prevention headers
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                # ✅ FIX 3: Referer makes it look like organic browser traffic
                "Referer": "https://www.google.com/search?q=kerala+gold+rate+today",
                "Upgrade-Insecure-Requests": "1",
            }

            log_message(f"Attempt {attempt}/{len(USER_AGENTS)}", "KERALA")

            # ✅ FIX 4: Small random delay so requests don't look robotic
            time.sleep(random.uniform(0.3, 0.8))

            response = session.get(url, headers=headers, timeout=20)

            if response.status_code == 200:
                log_message(f"✓ Connected with UA #{attempt}", "KERALA")
                rates = parse_keralagold_html(response.text)

                # ✅ FIX 5: Validate the fetched date matches today
                if rates:
                    is_fresh = validate_date_freshness(rates.get('date'), rates.get('date_raw'))
                    if not is_fresh:
                        log_message(f"⚠️ Stale data detected (page date: {rates.get('date')}), retrying...", "KERALA")
                        time.sleep(1)
                        continue  # Try next user agent
                    return rates

            time.sleep(0.5)

        except Exception as e:
            log_message(f"Attempt {attempt} failed: {str(e)[:50]}", "KERALA")
            time.sleep(0.5)

    log_message("⚠️ All attempts returned stale/failed data", "KERALA")
    return None


def validate_date_freshness(date_str, date_raw=None):
    """
    Check if fetched page date matches today or yesterday (gold rates update by morning).
    Returns True if fresh, False if stale.
    """
    if not date_str and not date_raw:
        # Can't validate, assume fresh to avoid false positives
        log_message("⚠️ Could not extract date from page, skipping date check", "KERALA")
        return True

    ist = pytz.timezone('Asia/Kolkata')
    today = datetime.now(ist)

    # Try to parse the date from the page
    try:
        # Format like "3 March 2026" or "03 March 2026"
        raw = date_raw or date_str
        page_date = datetime.strptime(raw.strip(), "%d %B %Y")

        # Allow today and yesterday (rates may not update until morning)
        today_date = today.date()
        page_date_only = page_date.date()

        days_diff = (today_date - page_date_only).days

        if days_diff == 0:
            log_message(f"✅ Date is today ({page_date_only})", "KERALA")
            return True
        elif days_diff == 1:
            # Check if it's before 9 AM IST — rates haven't updated yet
            if today.hour < 9:
                log_message(f"ℹ️ Yesterday's rate but before 9AM IST — acceptable", "KERALA")
                return True
            else:
                log_message(f"⚠️ Page shows yesterday's date ({page_date_only}), today is {today_date}", "KERALA")
                return False
        else:
            log_message(f"🚨 Page is {days_diff} days old! ({page_date_only})", "KERALA")
            return False

    except Exception as e:
        log_message(f"⚠️ Date parse failed ({date_str}): {e}", "KERALA")
        return True  # Can't parse = don't block, log and move on


def parse_keralagold_html(html):
    """Parse KeralaGold HTML - now extracts raw date for validation"""
    try:
        rates = {
            'date': None,
            'date_raw': None,      # ✅ NEW: raw date string for validation
            'today_rate': None,
            'morning': None,
            'afternoon': None,
            'evening': None
        }

        # Extract date — capture raw format like "3 March 2026"
        date_match = re.search(r'(\d{1,2}\s+[A-Za-z]+\s+\d{4})', html)
        if date_match:
            rates['date_raw'] = date_match.group(1)
            rates['date'] = date_match.group(1)

        # Method 1: "Today »" row — current day single rate
        today_pattern = r'<span class="red"><b>Today\s*&raquo;</b></span>.*?Rs\.\s*([\d,]+)'
        today_match = re.search(today_pattern, html, re.DOTALL)

        if today_match:
            rate = today_match.group(1).replace(',', '')
            rates['today_rate'] = rate
            log_message(f"Found today's rate: Rs.{rate}", "KERALA")
            return rates

        # Method 2: Time-specific rows
        today_rows = re.findall(r'(?s)<tr>.*?Today.*?</tr>', html)

        for row in today_rows:
            period = None
            if 'Morning' in row:
                period = 'morning'
            elif 'Afternoon' in row:
                period = 'afternoon'
            elif 'Evening' in row:
                period = 'evening'
            elif 'Noon' in row and not rates['afternoon']:
                period = 'afternoon'

            price_match = re.search(r'Rs\.\s*([\d,]+)', row)
            if price_match and period:
                price = price_match.group(1).replace(',', '')
                rates[period] = price

        if rates['today_rate'] or rates['morning'] or rates['afternoon'] or rates['evening']:
            return rates

        return None

    except Exception as e:
        log_message(f"Parse error: {e}", "KERALA")
        return None


# ============================================================================
# MONITORING LOGIC (unchanged)
# ============================================================================
def monitor_akgsma():
    log_message("🔍 Checking rates...", "AKGSMA")

    current_rates = fetch_akgsma_rates()
    if not current_rates:
        log_message("⚠️ Failed to fetch", "AKGSMA")
        return

    data = load_history('akgsma_rates_history.json')
    previous_rates = data.get('last_rates', {})

    changed = False
    changes = []

    for key in ['22K916', '18K750', 'Silver']:
        if key in current_rates and current_rates[key]:
            if key in previous_rates and previous_rates[key]:
                if current_rates[key] != previous_rates[key]:
                    changed = True
                    changes.append(f"{key}: ₹{previous_rates[key]} → ₹{current_rates[key]}")
            elif key not in previous_rates or not previous_rates.get(key):
                changed = True
                changes.append(f"{key}: NEW ₹{current_rates[key]}")

    if changed:
        log_message(f"🚨 CHANGED! {', '.join(changes)}", "AKGSMA")
        ist = pytz.timezone('Asia/Kolkata')
        data['history'].append({
            "timestamp": datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST"),
            "date": current_rates.get('date', 'Unknown'),
            "rates": current_rates,
            "changes": changes
        })
        if len(data['history']) > 200:
            data['history'] = data['history'][-200:]
    else:
        rates_str = ', '.join([f"{k}=₹{v}" for k, v in current_rates.items() if k != 'date' and v])
        log_message(f"✓ No change. {rates_str}", "AKGSMA")

    data['last_rates'] = current_rates
    save_history('akgsma_rates_history.json', data)


def monitor_keralagold():
    log_message("🔍 Checking rates...", "KERALA")

    current_rates = fetch_keralagold_rates()
    if not current_rates:
        log_message("⚠️ Failed to fetch", "KERALA")
        return

    data = load_history('keralagold_rates_history.json')
    previous_rates = data.get('last_rates', {})

    changed = False
    changes = []

    rate_fields = ['today_rate', 'morning', 'afternoon', 'evening']

    for field in rate_fields:
        if field in current_rates and current_rates[field]:
            curr = current_rates[field]
            prev = previous_rates.get(field)

            if prev and prev != curr:
                changed = True
                changes.append(f"{field.replace('_', ' ').title()}: Rs.{prev} → Rs.{curr}")
            elif not prev:
                changed = True
                changes.append(f"{field.replace('_', ' ').title()}: NEW Rs.{curr}")

    if changed:
        log_message(f"🚨 CHANGED! {', '.join(changes)}", "KERALA")
        ist = pytz.timezone('Asia/Kolkata')
        data['history'].append({
            "timestamp": datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST"),
            "date": current_rates.get('date', 'Unknown'),
            "rates": current_rates,
            "changes": changes
        })
        if len(data['history']) > 200:
            data['history'] = data['history'][-200:]
    else:
        rates_str = ', '.join([f"{k.replace('_', ' ').title()}=Rs.{v}"
                              for k, v in current_rates.items()
                              if k not in ('date', 'date_raw') and v])
        log_message(f"✓ No change. {rates_str}", "KERALA")

    data['last_rates'] = current_rates
    save_history('keralagold_rates_history.json', data)


def main():
    log_message("=" * 60, "SYSTEM")
    log_message("🚀 Combined Monitor Starting", "SYSTEM")
    log_message("=" * 60, "SYSTEM")

    monitor_akgsma()
    log_message("", "SYSTEM")
    monitor_keralagold()

    log_message("=" * 60, "SYSTEM")
    log_message("✅ Cycle complete", "SYSTEM")
    log_message("=" * 60, "SYSTEM")
    log_message("", "SYSTEM")

if __name__ == "__main__":
    main()