#GHOST-EM: Geo-locate anyone with a URL

Runs a Django-based location-sharing webpage from a single Python launcher, optionally exposed via a temporary ngrok HTTPS URL. The page explains that coordinates go to the session operator, and requires an explicit button click and browser geolocation permission. Coordinates are printed to the terminal, not saved to disk.

## Python 3.13

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

