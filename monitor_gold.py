import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import os
import pytz
import re
import time

# User agents for rotation (anti-block)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

def log_message(message, source="SYSTEM"):
    """Log with timestamp"""
    ist = pytz.timezone('Asia/Kolkata')
    timestamp = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")
    log_line = f"[{timestamp}] [{source}] {message}\n"
    print(log_line.strip())
    with open('monitoring_log.txt', 'a') as f:
        f.write(log_line)

def load_history(filename):
    """Load history from JSON file"""
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except:
            return {"last_rates": {}, "history": []}
    return {"last_rates": {}, "history": []}

def save_history(filename, data):
    """Save history to JSON file"""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

# ============================================================================
# AKGSMA FETCHER
# ============================================================================
def fetch_akgsma_rates():
    """Fetch AKGSMA rates"""
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
# KERALAGOLD FETCHER (WITH ANTI-BLOCK)
# ============================================================================
def fetch_keralagold_rates():
    """Fetch KeralaGold rates with anti-block techniques"""
    url = "https://www.keralagold.com/daily-gold-prices.htm"
    
    # Try multiple user agents
    for attempt, user_agent in enumerate(USER_AGENTS, 1):
        try:
            session = requests.Session()
            headers = {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
                "Cache-Control": "no-cache"
            }
            
            log_message(f"Attempt {attempt}/{len(USER_AGENTS)}", "KERALA")
            
            response = session.get(url, headers=headers, timeout=20)
            
            if response.status_code == 200:
                log_message(f"✓ Connected with UA #{attempt}", "KERALA")
                return parse_keralagold_html(response.text)
            
            time.sleep(0.5)
            
        except Exception as e:
            log_message(f"Attempt {attempt} failed: {str(e)[:50]}", "KERALA")
            time.sleep(0.5)
    
    log_message("All attempts failed", "KERALA")
    return None

def parse_keralagold_html(html):
    """Parse KeralaGold HTML for today's rates"""
    try:
        rates = {
            'date': None,
            'morning': None,
            'afternoon': None,
            'evening': None
        }
        
        # Extract date
        date_match = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', html)
        if date_match:
            rates['date'] = date_match.group(1)
        
        # Find all "Today" rows
        today_pattern = r'(?s)<tr>.*?Today.*?</tr>'
        rows = re.findall(today_pattern, html)
        
        for row in rows:
            period = None
            if 'Morning' in row:
                period = 'morning'
            elif 'Afternoon' in row:
                period = 'afternoon'
            elif 'Evening' in row:
                period = 'evening'
            elif 'Noon' in row and not rates['afternoon']:
                period = 'afternoon'
            
            # Extract price
            price_match = re.search(r'Rs\.\s*([\d,]+)', row)
            if price_match and period:
                price = price_match.group(1).replace(',', '')
                rates[period] = price
        
        if rates['morning'] or rates['afternoon'] or rates['evening']:
            return rates
        return None
        
    except Exception as e:
        log_message(f"Parse error: {e}", "KERALA")
        return None

# ============================================================================
# MONITORING LOGIC
# ============================================================================
def monitor_akgsma():
    """Monitor AKGSMA rates"""
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
    """Monitor KeralaGold rates"""
    log_message("🔍 Checking rates...", "KERALA")
    
    current_rates = fetch_keralagold_rates()
    if not current_rates:
        log_message("⚠️ Failed to fetch", "KERALA")
        return
    
    data = load_history('keralagold_rates_history.json')
    previous_rates = data.get('last_rates', {})
    
    changed = False
    changes = []
    
    for period in ['morning', 'afternoon', 'evening']:
        if period in current_rates and current_rates[period]:
            curr = current_rates[period]
            prev = previous_rates.get(period)
            
            if prev and prev != curr:
                changed = True
                changes.append(f"{period.capitalize()}: Rs.{prev} → Rs.{curr}")
            elif not prev:
                changed = True
                changes.append(f"{period.capitalize()}: NEW Rs.{curr}")
    
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
        rates_str = ', '.join([f"{k.capitalize()}=Rs.{v}" for k, v in current_rates.items() if k != 'date' and v])
        log_message(f"✓ No change. {rates_str}", "KERALA")
    
    data['last_rates'] = current_rates
    save_history('keralagold_rates_history.json', data)

# ============================================================================
# MAIN
# ============================================================================
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