import json
import os
from datetime import datetime
import pytz

def load_json(filename):
    """Load JSON data"""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except:
        return {"last_rates": {}, "history": []}

def format_price(price):
    """Format price with commas"""
    if not price:
        return "---"
    try:
        return f"{int(price):,}"
    except:
        return str(price)

def get_trend_and_change(history):
    """Get price trend and change amount from history"""
    if len(history) < 2:
        return "▶️", "No change", None
    
    try:
        latest = history[-1]
        previous = history[-2]
        
        # Compare first available rate
        for key in ['22K916', 'today_rate', 'morning']:
            if key in latest.get('rates', {}) and key in previous.get('rates', {}):
                curr = int(latest['rates'][key])
                prev = int(previous['rates'][key])
                diff = curr - prev
                
                if diff > 0:
                    return "📈", f"+₹{abs(diff)}", previous.get('timestamp')
                elif diff < 0:
                    return "📉", f"-₹{abs(diff)}", previous.get('timestamp')
                else:
                    return "▶️", "No change", None
    except:
        pass
    
    return "▶️", "---", None

def get_first_recorded(history):
    """Get first recorded timestamp"""
    if history and len(history) > 0:
        return history[0].get('timestamp', 'Unknown')
    return "Not available"

def generate_readme():
    """Generate README with live prices"""
    
    # Load data
    akgsma_data = load_json('akgsma_rates_history.json')
    kerala_data = load_json('keralagold_rates_history.json')
    
    akgsma_rates = akgsma_data.get('last_rates', {})
    kerala_rates = kerala_data.get('last_rates', {})
    akgsma_history = akgsma_data.get('history', [])
    kerala_history = kerala_data.get('history', [])
    
    # Get timestamps
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    timestamp = now.strftime("%d %B %Y, %I:%M %p IST")
    
    # Get trends and changes
    akgsma_trend, akgsma_change, akgsma_last_change = get_trend_and_change(akgsma_history)
    kerala_trend, kerala_change, kerala_last_change = get_trend_and_change(kerala_history)
    
    # Get first recorded times
    akgsma_first = get_first_recorded(akgsma_history)
    kerala_first = get_first_recorded(kerala_history)
    
    # AKGSMA prices
    gold_22k = format_price(akgsma_rates.get('22K916', '---'))
    gold_18k = format_price(akgsma_rates.get('18K750', '---'))
    silver = format_price(akgsma_rates.get('Silver', '---'))
    akgsma_date = akgsma_rates.get('date', '---')
    
    # Kerala prices
    kerala_rate = format_price(kerala_rates.get('today_rate') or 
                               kerala_rates.get('morning') or 
                               kerala_rates.get('afternoon') or 
                               kerala_rates.get('evening', '---'))
    kerala_date = kerala_rates.get('date', '---')
    
    # Generate README
    readme = f'''<div align="center">

# 💎 LIVE GOLD & SILVER RATES 💎

### 🔴 Real-Time Market Prices - India

---

## ⏰ **Last Updated**
### {timestamp}

🤖 **Auto-refreshes every 5 minutes via cron-job.org**

---

</div>

## 🏆 **AKGSMA** {akgsma_trend}
#### All Kerala Gold & Silver Merchants Association

<div align="center">

| 💰 COMMODITY | 💵 RATE (INR) | 📊 UNIT | 📈 CHANGE |
|:------------:|:-------------:|:-------:|:---------:|
| **🥇 GOLD 22K** | **₹ {gold_22k}** | per gram | {akgsma_change} |
| **🥈 GOLD 18K** | **₹ {gold_18k}** | per gram | {akgsma_change} |
| **⚪ SILVER 999** | **₹ {silver}** | per gram | {akgsma_change} |

**📅 Rate Date:** {akgsma_date}  
**🕐 First Tracked:** {akgsma_first}  
{f'**🔄 Last Changed:** {akgsma_last_change}' if akgsma_last_change else ''}

</div>

---

## 🌴 **KERALA GOLD** {kerala_trend}
#### Traditional Pavan Rate

<div align="center">

| 💰 MEASUREMENT | 💵 RATE (INR) | 📊 WEIGHT | 📈 CHANGE |
|:--------------:|:-------------:|:---------:|:---------:|
| **👑 1 PAVAN** | **₹ {kerala_rate}** | 8 grams (22K) | {kerala_change} |

**📅 Rate Date:** {kerala_date}  
**🕐 First Tracked:** {kerala_first}  
{f'**🔄 Last Changed:** {kerala_last_change}' if kerala_last_change else ''}

</div>

---

<div align="center">

## 📈 **MONITORING STATS**

| Source | Total Updates | Trend | Status |
|:------:|:-------------:|:-----:|:------:|
| **AKGSMA** | {len(akgsma_history)} records | {akgsma_trend} | 🟢 Live |
| **Kerala Gold** | {len(kerala_history)} records | {kerala_trend} | 🟢 Live |

---

## 🔔 **Monitoring Info**
```
🤖 Powered by GitHub Actions + cron-job.org
⏱️  Checks every 5 minutes (guaranteed)
♾️  Running 24/7/365
⚡ Real-time price tracking
📊 Full history preserved
```

---

### 📊 [View Full History](../../actions) • 🌟 [Star this repo](../../stargazers) • 🔧 [Report Issue](../../issues)

<sub>💡 Prices are fetched from official sources and updated automatically</sub>  
<sub>🔒 Reliable scheduling via cron-job.org (no GitHub Actions delays)</sub>

</div>

---

<div align="center">

![Visitors](https://visitor-badge.laobi.icu/badge?page_id=mybisdotsite.gold-rate-monitor)
![GitHub last commit](https://img.shields.io/github/last-commit/mybisdotsite/gold-rate-monitor?style=flat-square)
![Status](https://img.shields.io/badge/status-live-success?style=flat-square)
![Updates](https://img.shields.io/badge/updates-every_5_min-blue?style=flat-square)

</div>
'''
    
    # Write README
    with open('README.md', 'w', encoding='utf-8') as f:
        f.write(readme)
    
    print(f"✅ README updated with live prices at {timestamp}")

if __name__ == "__main__":
    generate_readme()