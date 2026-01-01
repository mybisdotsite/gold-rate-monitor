# Combined Gold Rate Monitor

Monitors gold rates from **2 sources** simultaneously:
- ✅ **AKGSMA** (akgsma.com) - 22K916, 18K750, Silver
- ✅ **KeralaGold** (keralagold.com) - 1 Pavan (8g, 22 Carat)

## Features
- 🔄 Runs **24/7** every 5 minutes
- 📊 **2 separate JSON files** for each source
- 🚀 Anti-block techniques for reliable fetching
- 📝 Detailed logging with timestamps
- 🤖 Auto-commits to GitHub

## Output Files
- `akgsma_rates_history.json` - AKGSMA rates
- `keralagold_rates_history.json` - KeralaGold rates
- `monitoring_log.txt` - Combined activity log

## What's Monitored

### AKGSMA (akgsma.com)
- 22K916 Gold
- 18K750 Gold  
- Silver 999

### KeralaGold (keralagold.com)
- 1 Pavan Morning rate
- 1 Pavan Afternoon rate
- 1 Pavan Evening rate

## How It Works
1. GitHub Actions runs every 5 minutes (24/7)
2. Fetches rates from both sites
3. Detects changes and logs them
4. Auto-commits updates to repository

## View Results
- Check Actions tab for real-time logs
- View JSON files for historical data
- View monitoring_log.txt for detailed logs