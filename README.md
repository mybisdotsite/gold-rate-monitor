# AKGSMA Gold Rate Monitor

Automated monitoring system for gold and silver rates from AKGSMA website.

## Features
- ✅ Monitors rates every 5 minutes (6-10 AM IST)
- ✅ Detects and logs all rate changes
- ✅ Stores complete history in JSON
- ✅ Runs automatically via GitHub Actions
- ✅ No database required

## How It Works
1. GitHub Actions runs the script every 5 minutes during market hours
2. Script fetches current rates from AKGSMA website
3. Compares with previous rates and detects changes
4. Logs all activity and stores history
5. Auto-commits changes back to repository

## Files
- `monitor_gold.py` - Main monitoring script
- `rates_history.json` - Historical rate data
- `monitoring_log.txt` - Detailed activity logs
- `.github/workflows/monitor.yml` - GitHub Actions workflow

## View Logs
- **Real-time**: Go to Actions tab in GitHub
- **Historical**: Check `monitoring_log.txt` in repository
- **Rate History**: Check `rates_history.json`

## Manual Run
```bash
python monitor_gold.py
```

## Setup
See SETUP.md for deployment instructions.
