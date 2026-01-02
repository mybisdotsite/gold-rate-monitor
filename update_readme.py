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

def get_trend(history):
    """Get price trend from history"""
    if len(history) < 2:
        return "▶️"
    
    try:
        latest = history[-1]
        previous = history[-2]
        
        # Compare first available rate
        for key in ['22K916', 'today_rate', 'morning']:
            if key in latest.get('rates', {}) and key in previous.get('rates', {}):
                curr = int(latest['rates'][key])
                prev = int(previous['rates'][key])
                if curr > prev:
                    return "📈"
                elif curr < prev:
                    return "📉"
                else:
                    return "▶️"
    except:
        pass
    
    return "▶️"

def generate_readme():
    """Generate README with live prices"""
    
    # Load data
    akgsma_data = load_json('akgsma_rates_history.json')
    kerala_data = load_json('keralagold_rates_history.json')
    
    akgsma_rates = akgsma_data.get('last_rates', {})
    kerala_rates = kerala_data.get('last_rates', {})
    
    # Get timestamps
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    timestamp = now.strftime("%d %B %Y, %I:%M %p IST")
    
    # Get trends
    akgsma_trend = get_trend(akgsma_data.get('history', []))
    kerala_trend = get_trend(kerala_data.get('history', []))
    
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

---

</div>

## 🏆 **AKGSMA** {akgsma_trend}
#### All Kerala Gold & Silver Merchants Association

<div align="center">

| 💰 COMMODITY | 💵 RATE (INR) | 📊 UNIT |
|:------------:|:-------------:|:-------:|
| **🥇 GOLD 22K** | **₹ {gold_22k}** | per gram |
| **🥈 GOLD 18K** | **₹ {gold_18k}** | per gram |
| **⚪ SILVER 999** | **₹ {silver}** | per gram |

**📅 Date:** {akgsma_date}

</div>

---

## 🌴 **KERALA GOLD** {kerala_trend}
#### Traditional Pavan Rate

<div align="center">

| 💰 MEASUREMENT | 💵 RATE (INR) | 📊 WEIGHT |
|:--------------:|:-------------:|:---------:|
| **👑 1 PAVAN** | **₹ {kerala_rate}** | 8 grams (22K) |

**📅 Date:** {kerala_date}

</div>

---

<div align="center">

## 📈 **PRICE HISTORY**

| Source | Last 5 Updates | Trend |
|:------:|:--------------:|:-----:|
| **AKGSMA** | {len(akgsma_data.get('history', []))} records | {akgsma_trend} |
| **Kerala Gold** | {len(kerala_data.get('history', []))} records | {kerala_trend} |

---

## 🔔 **Auto-Updates Every 5 Minutes**
```
🤖 Powered by GitHub Actions
♾️ Running 24/7/365
⚡ Real-time monitoring
```

---

### 📊 [View Full History](../../actions) • 🌟 [Star this repo](../../stargazers)

<sub>💡 Prices are fetched from official sources and updated automatically</sub>

</div>

---

<div align="center">

![Visitors](https://visitor-badge.laobi.icu/badge?page_id=mybisdotsite.gold-rate-monitor)
![GitHub last commit](https://img.shields.io/github/last-commit/mybisdotsite/gold-rate-monitor?style=flat-square)
![Status](https://img.shields.io/badge/status-live-success?style=flat-square)

</div>
'''
    
    # Write README
    with open('README.md', 'w', encoding='utf-8') as f:
        f.write(readme)
    
    print(f"✅ README updated with live prices at {timestamp}")

if __name__ == "__main__":
    generate_readme()