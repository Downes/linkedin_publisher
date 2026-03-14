# linkedin_publisher (/srv/apps/linkedin_publisher)

## Overview
Posts the daily OLDaily newsletter issue to LinkedIn as a newsletter article.
Triggered by gRSShopper after a successful SES newsletter send.

## Container
- Name: linkedin_publisher  Port: 5000 (internal only — no Caddy route)
- Not publicly reachable; only accessible from other containers on the `web` network

## Trigger
gRSShopper's `send_nl()` in `admin.cgi` POSTs to `http://linkedin_publisher:5000/publish`
with a `token=` form field (matches `PUBLISH_TOKEN` in `.env`).
The endpoint returns 202 immediately; Selenium runs in a background thread.

## Volumes
- ./chrome_profile → /app/chrome_profile  (persistent LinkedIn session — do not delete)
- ./data           → /app/data            (posted.json duplicate guard + debug screenshots)

## Network
- web (external) — shared with grsshopper and other apps

## Config
- `.env` (copy from `.env.example`, never commit)
- Key vars: LINKEDIN_EMAIL, LINKEDIN_PASSWORD, NEWSLETTER_NAME, SOURCE_URL, PUBLISH_TOKEN, VNC_PASSWORD

## Build & restart
```bash
cd /srv/apps/linkedin_publisher
docker compose build
docker compose up -d
```

## Language
Python 3.11. Uses Chromium from Debian apt (not webdriver-manager).
Chromium binary: /usr/bin/chromium  ChromeDriver: /usr/bin/chromedriver

## Debugging
Failed runs save screenshots and page HTML to `./data/debug_*.png` / `.html`.
Check with: `docker logs linkedin_publisher`
Check last result: `curl http://172.18.0.x:5000/health` (get IP with `docker inspect linkedin_publisher`)

---

## Sustainability

### Session renewal (expect every 1–2 months)
When the LinkedIn session expires, runs will fail with a login/checkpoint error in the logs.
The VNC tooling is permanently baked into the image for exactly this purpose.

**Steps to renew:**
1. Add `5900:5900` to the `ports:` section of `docker-compose.yml`
2. Add a `VNC_PASSWORD` to `.env` if not already set
3. `docker compose up -d`
4. Connect via VNC viewer to `158.69.209.43:5900` using the VNC_PASSWORD
5. In the xterm window, run:
   ```bash
   chromium --no-sandbox --disable-dev-shm-usage \
     --user-data-dir=/app/chrome_profile --profile-directory=Default \
     https://www.linkedin.com/login
   ```
6. Log in to LinkedIn in the browser window (complete any 2FA)
7. Close the browser window cleanly (File → Exit or window close button)
8. Remove `5900:5900` from `docker-compose.yml`
9. `docker compose up -d`

### Duplicate guard
`./data/posted.json` tracks published issues by title. If you need to republish an issue,
remove its entry from that file before triggering `/publish`.

### LinkedIn UI changes
If LinkedIn changes their article editor, XPath selectors in `publisher.py` will break.
Debug screenshots in `./data/` will show exactly where it failed.
Look for the `_find_headline_element`, `set_body`, and `select_newsletter_and_publish`
functions — those are the most likely to need updating.

### Watchdog timeout
`PUBLISH_TIMEOUT` env var (default 720s / 12 min) kills a hung browser and resets the
running flag. Adjust in `.env` if needed.

### Monitoring
No automated alerting yet. To check manually:
```bash
docker logs linkedin_publisher | tail -20
curl -s http://$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' linkedin_publisher):5000/health
```
