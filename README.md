#GHOST-EM: Geo-locate anyone with a URL

Runs a Django-based location-sharing webpage from a single Python launcher, optionally exposed via a temporary ngrok HTTPS URL. The page explains that coordinates go to the session operator, and requires an explicit button click and browser geolocation permission. Coordinates are printed to the terminal, not saved to disk.

## Python 3.13

### Approved accounts and Turnstile

The homepage and RF map require an active Django account. An operator must
provision accounts in Django. The administrator dashboard requires a superuser.

On Render, set `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` before deploying
this version. In Cloudflare, authorize the hostname visitors use to sign in.
Both sign-in routes require a valid Turnstile challenge on Render and share an
eight-attempt limit per account name per minute. Local development can leave
both keys unset to test account authentication without the widget.

### Running locally

```bash
cd GHOST-EM
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

For geolocation from another device, use HTTPS:

```bash
ngrok config add-authtoken YOUR_NGROK_TOKEN
python app.py --tunnel
```

