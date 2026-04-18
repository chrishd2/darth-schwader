# Schwab Developer Setup Walkthrough

This is required before Phase-1 code can authenticate. The `schwab_oauth_login.py` script automates the rest, but Schwab requires a one-time manual app registration.

## Step 1 — Create a Schwab Developer account
1. Go to <https://developer.schwab.com>.
2. Click **Register** in the top-right. Use the same email tied to your brokerage account.
3. Verify email + complete profile.
4. Log in. You'll land on the Developer Portal dashboard.

## Step 2 — Create an App
1. From the dashboard, click **Dashboard → Create App**.
2. Fill in:
   - **App Name**: `darth-schwader-local` (any name; this is for your reference)
   - **Description**: "Personal automated options trading bot — local single-user use."
   - **Callback URL** (this matches our config): `https://127.0.0.1:8000/api/v1/broker/oauth/callback`
   - **API Products**: select **Accounts and Trading Production** AND **Market Data Production**.
   - **Order Limit**: start at the lowest (typically 120 req/min). You can request more later.
3. Submit.

## Step 3 — Wait for app approval
- Approval is **manual** by Schwab and typically takes **1–3 business days**.
- App status will move from `Approved Pending` → `Ready For Use`.
- You'll get an email; or check the dashboard.

## Step 4 — Capture credentials
Once `Ready For Use`:
1. Open your app from the dashboard.
2. Copy **App Key** → this is `SCHWAB_CLIENT_ID`.
3. Copy **Secret** → this is `SCHWAB_CLIENT_SECRET`. Treat it like a password.
4. Note your **Callback URL** matches the one in `.env.example`.

## Step 5 — Confirm options approval level on the brokerage side
1. Log in to schwab.com → Service → Account Settings → Options Approval.
2. Confirm you have **at least Tier 2**.
3. **Request Tier 3** if you want iron condors or credit spreads in this cash account.
4. Tier 3 approval can take 1–5 business days.

## Step 6 — Local HTTPS for the callback
Schwab requires `https://`.

- Recommended: use `mkcert` to issue a locally-trusted certificate for `127.0.0.1`.
- Alternative: use a self-signed certificate and accept the browser warning during the one-time auth flow.
- Setup commands ship in `scripts/bootstrap_local.sh`, which installs `mkcert` if needed and writes local certs into `certs/`.

## Step 7 — Run the OAuth bootstrap

```bash
python scripts/schwab_oauth_login.py
```

The script opens your browser, completes Schwab login and consent, and persists encrypted tokens into SQLite. You only do this once; the token watchdog rotates refresh state afterward.
