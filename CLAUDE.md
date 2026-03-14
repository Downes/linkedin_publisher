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
- Key vars: LINKEDIN_EMAIL, LINKEDIN_PASSWORD, NEWSLETTER_NAME, SOURCE_URL, PUBLISH_TOKEN

## Chrome profile / first-time login
The chrome_profile directory stores the LinkedIn session cookie.
If the profile is empty (first run or session expired):
1. Copy your working chrome_profile from Windows: `scp -r E:\path\to\chrome_profile ubuntu@158.69.209.43:/srv/apps/linkedin_publisher/`
2. Or rebuild the session by temporarily setting HEADLESS=false and running with X11 forwarding

## Debugging
Failed runs save screenshots and page HTML to `./data/debug_*.png` / `.html`.
Check with: `docker logs linkedin_publisher`

## Language
Python 3.11. Uses Chromium from Debian apt (not webdriver-manager).
Chromium binary: /usr/bin/chromium  ChromeDriver: /usr/bin/chromedriver

## Build & restart
```bash
cd /srv/apps/linkedin_publisher
docker compose build
docker compose up -d
```
