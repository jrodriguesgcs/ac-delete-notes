# 🚀 ActiveCampaign Note Deletion via GitHub Actions

Automatically delete all deal notes created by User ID 112 using GitHub Actions, running continuously until complete.

## ✨ Features

- ✅ **Automatic Resume**: Saves progress between runs, never deletes the same note twice
- ✅ **6-Hour Batches**: Runs every 6 hours automatically until all notes deleted
- ✅ **10 req/s Rate Limit**: Optimized for maximum speed
- ✅ **Progress Tracking**: Full logs and state saved as artifacts
- ✅ **Email Notifications**: Optional email updates on progress
- ✅ **FREE**: Runs on GitHub's free tier (2,000 minutes/month)

## 📋 Setup Instructions

### 1. Create Repository Structure

Create a new GitHub repository with this structure:

```
your-repo/
├── .github/
│   └── workflows/
│       └── delete-notes.yml
├── delete_notes.py
└── README.md
```

### 2. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret Name | Value | Required |
|------------|-------|----------|
| `ACTIVECAMPAIGN_API_KEY` | Your ActiveCampaign API key | ✅ Yes |
| `EMAIL_USERNAME` | Gmail for notifications | ❌ Optional |
| `EMAIL_PASSWORD` | Gmail app password | ❌ Optional |
| `NOTIFICATION_EMAIL` | Email to receive updates | ❌ Optional |

**To get your ActiveCampaign API Key:**
1. Log into ActiveCampaign
2. Go to Settings → Developer
3. Copy your API Key

### 3. Enable GitHub Actions

1. Go to **Actions** tab in your repository
2. Click "I understand my workflows, go ahead and enable them"

### 4. Start the Workflow

**Option A: Manual Start**
1. Go to **Actions** tab
2. Select "Delete ActiveCampaign Deal Notes"
3. Click "Run workflow"
4. Leave defaults and click "Run workflow"

**Option B: Automatic Schedule**
- The workflow will run every 6 hours automatically once enabled
- Edit the `cron` schedule in the workflow file if needed

## 📊 Monitoring Progress

### View Logs
1. Go to **Actions** tab
2. Click on any running/completed workflow
3. Click "delete-notes" job to see detailed logs

### Download State Files
1. Go to completed workflow run
2. Scroll to **Artifacts** section
3. Download `progress-state-batch-X` to see:
   - `progress_state.json`: Current progress data
   - `deletion_log.txt`: Detailed execution log

### Check Progress State
```json
{
  "processed_note_ids": [...],
  "total_deleted": 150000,
  "total_failed": 12,
  "batch_number": 25,
  "remaining_notes": 5100000
}
```

## ⏱️ Time Estimates

With **10 requests/second** and **5.25M notes**:

| Metric | Value |
|--------|-------|
| Total time needed | ~6.1 days |
| Notes per 6-hour batch | ~210,000 |
| Number of batches | ~25 batches |
| Expected completion | 6-7 days |

## 🎯 How It Works

1. **Fetch Phase**: Gets all notes from ActiveCampaign (batches of 100)
2. **Filter**: Identifies Deal notes by User 112, skips already-processed
3. **Delete Phase**: Deletes notes in parallel (20 workers, 10 req/s)
4. **Save State**: Records all processed note IDs
5. **Repeat**: Automatically runs again in 6 hours

## 🔧 Configuration

Edit these in `.github/workflows/delete-notes.yml`:

```yaml
env:
  # Run every 6 hours (adjust if needed)
  schedule:
    - cron: '0 */6 * * *'
  
  # In the delete step:
  RATE_LIMIT: '10'           # Requests per second
  MAX_WORKERS: '20'          # Parallel workers
  NOTES_PER_RUN: '0'         # 0 = unlimited, or set max per batch
```

## 🚨 Important Notes

### Rate Limits
- Default: 10 req/s (if you got approval from ActiveCampaign)
- Standard: 5 req/s (without approval - change RATE_LIMIT to '5')

### GitHub Actions Limits
- **Free tier**: 2,000 minutes/month
- Each 6-hour run uses 360 minutes
- Can run ~5.5 batches/month on free tier
- **Upgrade to paid** if needed (~$0.008/minute)

### Safety Features
- ✅ Idempotent: Never deletes same note twice
- ✅ Crash-safe: Resume from exact point if interrupted
- ✅ Audit trail: Complete logs of all operations

## 📧 Email Notifications (Optional)

To receive email updates:

1. Create a Gmail App Password:
   - Go to Google Account → Security
   - Enable 2FA
   - App Passwords → Generate new password
   
2. Add secrets:
   - `EMAIL_USERNAME`: your-email@gmail.com
   - `EMAIL_PASSWORD`: the app password
   - `NOTIFICATION_EMAIL`: where to send notifications

## 🛑 Stopping the Process

### Pause Temporarily
1. Go to **Actions** tab
2. Click "Delete ActiveCampaign Deal Notes"
3. Click "..." → "Disable workflow"

### Stop Permanently
1. Delete the workflow file from `.github/workflows/`
2. Or disable the workflow (as above)

## 🐛 Troubleshooting

### Workflow Not Running
- Check if Actions are enabled in Settings
- Verify secrets are added correctly
- Check workflow syntax is valid YAML

### API Errors (429 - Too Many Requests)
- Rate limit exceeded
- Reduce `RATE_LIMIT` value in workflow

### Progress Not Saving
- Check artifact uploads in workflow logs
- Artifacts expire after 30 days by default

## 📈 Example Progress

```
Batch 1:  210,000 deleted (4.0% complete)
Batch 2:  420,000 deleted (8.0% complete)
Batch 3:  630,000 deleted (12.0% complete)
...
Batch 25: 5,250,000 deleted (100% complete) ✅
```

## 💡 Tips

1. **Monitor First Batch**: Watch the first run to ensure everything works
2. **Check Artifacts**: Download progress files after first batch
3. **Adjust Schedule**: Can run more/less frequently if needed
4. **Manual Triggers**: Use "Run workflow" for immediate execution
5. **Keep Repo Private**: Contains sensitive API operations

## 🎉 Completion

When all notes are deleted:
- Workflow will log "NO MORE NOTES TO DELETE!"
- You can disable the workflow
- Download final artifacts for audit records

## 📞 Support

If issues arise:
- Check workflow logs first
- Verify ActiveCampaign API key is valid
- Ensure rate limit hasn't been exceeded
- Review progress_state.json for current status

---

**Estimated Cost**: FREE (on GitHub Free tier if completed in ~1 month)
**Estimated Time**: 6-7 days
**Hands-off**: Fully automated after initial setup! 🚀
