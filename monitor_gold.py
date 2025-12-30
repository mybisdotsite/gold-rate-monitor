import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import os
import pytz

# Configuration
URL = "http://akgsma.com/index.php"

def get_current_rates():
    """Fetch current gold rates from website"""
    try:
        response = requests.get(URL, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract rates from the HTML structure
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
                    # Extract date from format "Today's Rate (30/12/2025)"
                    if '(' in text and ')' in text:
                        rates['date'] = text.split('(')[1].split(')')[0]
        
        return rates
    except Exception as e:
        print(f"❌ Error fetching rates: {e}")
        return None

def load_previous_rates():
    """Load previous rates from file"""
    if os.path.exists('rates_history.json'):
        try:
            with open('rates_history.json', 'r') as f:
                return json.load(f)
        except:
            return {"last_rates": {}, "history": []}
    return {"last_rates": {}, "history": []}

def save_rates(data):
    """Save rates to file"""
    with open('rates_history.json', 'w') as f:
        json.dump(data, f, indent=2)

def log_check(message):
    """Append to log file"""
    ist = pytz.timezone('Asia/Kolkata')
    timestamp = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")
    log_line = f"[{timestamp}] {message}\n"
    
    print(log_line.strip())
    
    with open('monitoring_log.txt', 'a') as f:
        f.write(log_line)

def main():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    
    log_check(f"🔍 Starting rate check...")
    
    # Get current rates
    current_rates = get_current_rates()
    
    if not current_rates:
        log_check("⚠️ Failed to fetch rates")
        return
    
    # Load previous data
    data = load_previous_rates()
    previous_rates = data.get('last_rates', {})
    
    # Check for changes
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
        log_check(f"🚨 RATE CHANGED! {', '.join(changes)}")
        
        # Add to history
        history_entry = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date": current_rates.get('date', 'Unknown'),
            "rates": current_rates,
            "changes": changes
        }
        data['history'].append(history_entry)
        
        # Keep only last 100 entries
        if len(data['history']) > 100:
            data['history'] = data['history'][-100:]
    else:
        rates_display = []
        for key in ['22K916', '18K750', 'Silver']:
            if key in current_rates and current_rates[key]:
                rates_display.append(f"{key}=₹{current_rates[key]}")
        log_check(f"✓ No change. Current: {', '.join(rates_display)}")
    
    # Update last rates
    data['last_rates'] = current_rates
    save_rates(data)
    
    log_check("✅ Check complete\n")

if __name__ == "__main__":
    main()
