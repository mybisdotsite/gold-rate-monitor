# Deployment Instructions

## Step 1: Push to GitHub
```bash
# Already initialized! Just need to:
git remote add origin https://github.com/YOUR_USERNAME/gold-rate-monitor.git
git branch -M main
git push -u origin main
```

## Step 2: Enable GitHub Actions
1. Go to your repository on GitHub
2. Click "Actions" tab
3. Click "I understand my workflows, go ahead and enable them"

## Step 3: Test
1. Go to Actions tab
2. Click "Gold Rate Monitor" workflow
3. Click "Run workflow" → "Run workflow"
4. Watch it run!

## Step 4: Monitor
- Check Actions tab for real-time logs
- View `monitoring_log.txt` for history
- View `rates_history.json` for rate changes

## Troubleshooting
- If workflow doesn't run: Check Actions are enabled
- If script fails: Check logs in Actions tab
- If no changes detected: Check website structure hasn't changed

## Customize Schedule
Edit `.github/workflows/monitor.yml` and change the cron:
```yaml
- cron: '*/5 0-4 * * *'  # Every 5 min, 6-10 AM IST
```
