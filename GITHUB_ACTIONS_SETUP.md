# GitHub Actions Setup — Health Dashboard

The workflow runs **every hour** and fetches data from Strava and Whoop automatically.

## Step 1: Fix Whoop config (one-time)

Your `whoop_config.json` has a truncated access token. On your local PC, run:

```bash
python whoop_setup.py
```

This will open a browser for authorization and write a fresh token.

## Step 2: Create a Fine-Grained Personal Access Token

1. Go to: https://github.com/settings/personal-access-tokens/new
2. Name: `health-dashboard-actions`
3. Expiration: pick the longest option (1 year)
4. Repository access: **Only select repositories** → `kristian-koa/health-dashboard`
5. Permissions:
   - **Repository permissions → Secrets** → Read and write
6. Click **Generate token** and copy it

## Step 3: Add GitHub Secrets

Go to: https://github.com/kristian-koa/health-dashboard/settings/secrets/actions

Add these 3 secrets:

| Secret name      | Value                                                  |
| ---------------- | ------------------------------------------------------ |
| `GH_PAT`         | The fine-grained PAT from Step 2                       |
| `STRAVA_CONFIG`  | Full contents of your local `strava_config.json` file  |
| `WHOOP_CONFIG`   | Full contents of your local `whoop_config.json` file   |

To get the config contents, run locally:

```bash
cat strava_config.json
cat whoop_config.json
```

Copy-paste each into the corresponding secret.

## Step 4: Push the workflow

```bash
git add .github/workflows/fetch-data.yml GITHUB_ACTIONS_SETUP.md
git commit -m "Add GitHub Actions workflow for hourly data fetch"
git push
```

## Step 5: Test it

Go to **Actions** tab → **Fetch Health Data** → **Run workflow** (manual trigger).

Check the run log to confirm both Strava and Whoop fetches succeed.

## How it works

- Runs hourly (at :10 past each hour)
- Reconstructs config files from GitHub Secrets
- Runs `strava_fetch.py` and `whoop_fetch.py`
- Pushes refreshed OAuth tokens back to secrets (so they survive between runs)
- Commits updated `activities.json` and `whoop_data.json` to the repo
- Skips commit if no data changed

## Cost

GitHub Actions Free tier includes 2,000 minutes/month for private repos.
Hourly runs at ~30s each ≈ 360 min/month — well within the free limit.
