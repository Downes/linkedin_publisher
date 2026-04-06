#!/usr/bin/env python3
"""
LinkedIn OLDaily publisher.

Fetches OLDaily.htm, extracts the intro and post content, then drives
the LinkedIn article editor via Selenium to publish a newsletter issue.

Selenium flow taken from li_newsletter_selenium.py (known working).
Content extraction replaces the RSS fetch with direct HTML parsing.
"""

import os, json, time, sys, html, re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Comment, NavigableString
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv()

# ===================== CONFIG =====================

LINKEDIN_EMAIL    = os.getenv("LINKEDIN_EMAIL")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD")
NEWSLETTER_NAME   = os.getenv("NEWSLETTER_NAME", "OLDaily")
SOURCE_URL        = os.getenv("SOURCE_URL", "https://www.downes.ca/news/OLDaily.htm")
COMPOSER_URL      = os.getenv("COMPOSER_URL", (
    "https://www.linkedin.com/article/new/"
    "?author=urn%3Ali%3Afsd_profile%3AACoAAAAI52YBB6qnG3mdwHncS6-Lx5nnkx5Rz8I"
))
HEADLESS          = os.getenv("HEADLESS", "true").lower() == "true"
PROFILE_DIR       = str(Path(os.getenv("PROFILE_DIR", "/app/chrome_profile")).resolve())
POSTED_PATH       = Path(os.getenv("POSTED_PATH", "/app/data/posted.json"))
TIMEZONE          = os.getenv("TIMEZONE", "America/Toronto")

assert NEWSLETTER_NAME, "Set NEWSLETTER_NAME in .env"
assert SOURCE_URL,      "Set SOURCE_URL in .env"

# ===================== CONTENT EXTRACTION =====================

# Tags and attributes to keep in the LinkedIn body
ALLOWED_TAGS = {
    "p", "h1", "h2", "h3", "h4",
    "ul", "ol", "li", "br", "strong", "em", "b", "i",
    "blockquote", "a", "hr", "div", "img",
}
ALLOWED_ATTRS = {
    "a":   {"href"},
    "img": {"src", "alt", "width"},
    "div": {"class", "style"},
}


def absolutize_links(soup, base):
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", href):
            a["href"] = urljoin(base, href)


def sanitize(html_str, base_url):
    """Strip disallowed tags/attrs; make links absolute."""
    soup = BeautifulSoup(html_str, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    absolutize_links(soup, base_url)
    for tag in list(soup.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        allowed = ALLOWED_ATTRS.get(tag.name, set())
        for attr in list(tag.attrs.keys()):
            if attr not in allowed:
                del tag.attrs[attr]
        if tag.name == "a" and not tag.get("href"):
            tag.unwrap()
    # Remove paragraphs that contain only whitespace / <br> tags
    for p in soup.find_all("p"):
        has_content = any(
            (hasattr(c, "name") and c.name not in ("br",)) or
            (isinstance(c, str) and c.strip())
            for c in p.children
        )
        if not has_content:
            p.decompose()

    container = soup.body or soup
    return "".join(str(c) for c in container.children if getattr(c, "name", None)).strip()


def _make_footer():
    year = datetime.now().year
    return f"""<hr>
<p>We publish six to eight or so short posts every weekday linking to the best, most interesting
and most important pieces of content in the field. Read more about
<a href="https://www.downes.ca/news/about_old.htm">what we cover</a>.
We also list papers and articles by Stephen Downes and his presentations from around the world.</p>
<p>There are many ways to read OLDaily; pick whatever works best for you:</p>
<ul>
<li>Read in your web browser on <a href="https://www.downes.ca/news/OLDaily.htm">this web page</a>, updated weekdays</li>
<li>Receive a daily or weekly email newsletter by <a href="https://www.downes.ca/subscribe.htm">subscribing here</a></li>
<li>Subscribe to the <a href="https://www.downes.ca/news/OLDaily.xml">RSS feed</a> using your favourite feed reader</li>
<li>Follow <a href="https://mastodon.social/@oldaily">@OLDaily@mastodon.social</a> on Mastodon or elsewhere in the fediverse</li>
<li>Follow <a href="https://bsky.app/profile/oldaily.bsky.social">@OLDaily</a> on Bluesky</li>
<li>Read OLDaily as a <a href="https://www.linkedin.com/newsletters/7369381037719646208/">LinkedIn Newsletter</a></li>
<li>Integrate the open API using the <a href="https://www.downes.ca/news/OLDaily.json">JSON feed</a></li>
</ul>
<p>Know a friend who might enjoy this newsletter? Feel free to forward OLDaily to your colleagues.
If you received this issue from a friend and would like a free subscription of your own,
you can join our mailing list. <a href="https://www.downes.ca/subscribe.htm">Click here to subscribe</a>.</p>
<p>Copyright {year} Stephen Downes. Contact: <a href="mailto:stephen@downes.ca">stephen@downes.ca</a></p>
<p>This work is licensed under a
<a href="https://creativecommons.org/licenses/by-nc-sa/3.0/">Creative Commons License</a>.</p>"""


def extract_content(html_text, source_url):
    """
    Parse OLDaily.htm and return (title, body_html).

    Title:   "OLDaily — Mar 13, 2026"  (from the byline date, or today)
    Body:    Intro paragraph + "100% human-authored" + all post divs
    """
    soup = BeautifulSoup(html_text, "lxml")

    # --- Date / title ---
    byline = soup.find(class_="email_byline")
    issue_date = ""
    if byline:
        # byline text: "by Stephen Downes\nMar 13, 2026"
        for line in reversed(byline.get_text("\n").splitlines()):
            line = line.strip()
            if line and any(ch.isdigit() for ch in line):
                issue_date = line
                break

    try:
        tz = ZoneInfo(TIMEZONE)
    except Exception:
        tz = None
    now = datetime.now(tz) if tz else datetime.now()
    title = f"OLDaily \u2014 {issue_date}" if issue_date else f"OLDaily \u2014 {now.strftime('%b %d, %Y')}"

    # --- Body ---
    email_page = soup.find(class_="email_page") or soup.body or soup

    body_parts = []

    # Intro + "100% human-authored" combined into one paragraph
    intro_text = ""
    intro = email_page.find("div", style=lambda s: s and "font-size:small" in s)
    if intro:
        intro_text = intro.get_text(strip=True)

    for b in email_page.find_all("b"):
        if "100%" in b.get_text():
            human_authored = b.get_text(strip=True)
            if intro_text:
                body_parts.append(f"<p>{intro_text} <b>{human_authored}</b></p>")
            else:
                body_parts.append(f"<p><b>{human_authored}</b></p>")
            break

    body_parts.append('<div style="border: 1pt solid brown; padding: 0.75em 1em; line-height: 1.4;">'
                      '  Support OLDaily. A paid subscription keeps OLDaily free and open for all. '
                      '  We\'re now at <b>10%</b> of our May 15 target. '
                      '  <a href="https://www.downes.ca/news/about_old.htm#support">Click here to support OLDaily.</a>'
                      '</div>')

    body_parts.append("<hr>")

    # Post divs: collect all div children of email_page except header and intro
    for child in email_page.children:
        if not hasattr(child, "name") or child.name != "div":
            continue
        classes = child.get("class") or []
        style   = child.get("style") or ""
        if "email_head" in classes:
            continue  # page header — skip
        if "font-size:small" in style:
            continue  # intro div — already captured
        # Separator divs (contain only an <hr>) and post content divs — keep both
        body_parts.append(str(child))

    body_parts.append(_make_footer())
    body_html = sanitize("\n".join(body_parts), source_url)

    # Post-processing: for each post div, add comma after title and remove
    # the internal <hr> that separates the title/byline from the description
    soup_body = BeautifulSoup(body_html, "lxml")
    for div in soup_body.find_all("div"):
        first_strong = div.find("strong")
        if not (first_strong and first_strong.find("a")):
            continue  # not a post div
        first_strong.insert_after(NavigableString(","))
        first_hr = div.find("hr")
        if first_hr:
            first_hr.decompose()
    container = soup_body.body or soup_body
    body_html = "".join(str(c) for c in container.children
                        if getattr(c, "name", None)).strip()

    return title, body_html


# ===================== DUPLICATE GUARD =====================

def load_posted():
    if POSTED_PATH.exists():
        try:
            return set(json.loads(POSTED_PATH.read_text()))
        except Exception:
            return set()
    return set()


def save_posted(s):
    POSTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSTED_PATH.write_text(json.dumps(sorted(list(s)), indent=2))


# ===================== SELENIUM HELPERS =====================
# (logic from li_newsletter_selenium.py — known to work)

def make_driver():
    Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    # Remove stale lock files left by manual Chrome sessions
    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        Path(PROFILE_DIR, lock).unlink(missing_ok=True)
    options = Options()
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-notifications")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if HEADLESS:
        options.add_argument("--headless=new")
    # Use apt-installed Chromium; chromedriver is at /usr/bin/chromedriver
    options.binary_location = "/usr/bin/chromium"
    drv = webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=options)
    drv.set_page_load_timeout(120)
    drv.implicitly_wait(2)
    return drv


def wait(drv, timeout=45):
    return WebDriverWait(drv, timeout)


def logged_in(drv):
    try:
        wait(drv, 8).until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']")))
        return True
    except Exception:
        return False


def _page_state(drv):
    """Return a short summary of the current page for logging."""
    try:
        return f"URL={drv.current_url!r}  title={drv.title!r}"
    except Exception:
        return "(page state unavailable)"


def ensure_login(drv):
    print("[login] Navigating to linkedin.com/login …")
    drv.get("https://www.linkedin.com/login")
    time.sleep(1.5)
    print(f"[login] {_page_state(drv)}")
    if logged_in(drv):
        print("[login] Already logged in.")
        return
    print(f"[login] Not logged in. {_page_state(drv)}")
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        print("[login] No credentials; waiting for manual login…")
        for _ in range(150):
            if logged_in(drv):
                print("[login] Detected logged-in state.")
                return
            time.sleep(1)
        return
    try:
        print(f"[login] Filling credentials for {LINKEDIN_EMAIL} …")
        email = wait(drv).until(EC.presence_of_element_located((By.ID, "username")))
        pwd   = drv.find_element(By.ID, "password")
        email.clear(); email.send_keys(LINKEDIN_EMAIL)
        pwd.clear();   pwd.send_keys(LINKEDIN_PASSWORD); pwd.send_keys(Keys.ENTER)
        print("[login] Credentials submitted — waiting for feed …")
        for i in range(120):
            if i % 10 == 0:
                print(f"[login] {i}s elapsed … {_page_state(drv)}")
            if logged_in(drv):
                print("[login] Success.")
                return
            time.sleep(1)
        print(f"[login] Gave up waiting for login. {_page_state(drv)}")
        debug_dump(drv, "debug_login")
    except Exception as e:
        print(f"[login] warning: {e}")
        debug_dump(drv, "debug_login")


def ready_state_complete(drv, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if drv.execute_script("return document.readyState") == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def click_if_visible(drv, xpaths, pause=0.25):
    for xp in xpaths:
        try:
            el = WebDriverWait(drv, 3).until(EC.element_to_be_clickable((By.XPATH, xp)))
            drv.execute_script("arguments[0].click();", el)
            time.sleep(pause)
        except Exception:
            pass


def editor_ready(drv):
    selectors = [
        "//div[@contenteditable='true' and (@data-placeholder='Add a headline' or @data-placeholder='Add headline')]",
        "//h1[@contenteditable='true']",
        "//div[@role='textbox' and contains(@aria-label,'headline')]",
        "//div[@contenteditable='true' and contains(@aria-label,'headline')]",
        "//div[@contenteditable='true' and contains(@data-placeholder,'Start writing')]",
        "//div[@role='textbox' and @contenteditable='true' and not(ancestor::header)]",
        "//div[@contenteditable='true' and not(ancestor::header)]",
    ]
    for xp in selectors:
        if drv.find_elements(By.XPATH, xp):
            return True
    return False


def try_composer_url(drv):
    print(f"[composer] Navigating to COMPOSER_URL …")
    drv.get(COMPOSER_URL)
    ready_state_complete(drv, 60)
    print(f"[composer] {_page_state(drv)}")
    click_if_visible(drv, [
        "//button[.//span[contains(.,'Accept') or contains(.,'Agree')]]",
        "//button[.//span[contains(.,'Got it') or contains(.,'OK')]]",
        "//button[.//span[contains(.,'Skip') or contains(.,'Not now')]]",
        "//button[normalize-space()='Accept']",
        "//button[normalize-space()='Got it']",
        "//button[normalize-space()='Skip']",
    ])
    t0 = time.time()
    while time.time() - t0 < 75:
        if editor_ready(drv):
            print("[composer] Editor ready via COMPOSER_URL.")
            return True
        elapsed = time.time() - t0
        if int(elapsed) % 15 == 0 and elapsed > 1:
            print(f"[composer] Still waiting for editor… {elapsed:.0f}s  {_page_state(drv)}")
        time.sleep(0.5)
    print(f"[composer] COMPOSER_URL strategy failed. {_page_state(drv)}")
    return False


def try_feed_then_click_write_article(drv):
    print("[composer] Trying feed → Write article …")
    drv.get("https://www.linkedin.com/feed/")
    ready_state_complete(drv, 60)
    print(f"[composer] Feed loaded: {_page_state(drv)}")
    click_if_visible(drv, [
        "//button[.//span[contains(.,'Accept') or contains(.,'Agree')]]",
        "//button[.//span[contains(.,'Got it') or contains(.,'OK')]]",
    ])
    candidates = [
        "//a[contains(@href,'/article/new')]",
        "//a[.//span[contains(.,'Write article')]]",
        "//button[.//span[contains(.,'Write article')]]",
    ]
    for xp in candidates:
        try:
            el = wait(drv, 20).until(EC.element_to_be_clickable((By.XPATH, xp)))
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            drv.execute_script("arguments[0].click();", el)
            break
        except Exception:
            pass
    if len(drv.window_handles) > 1:
        drv.switch_to.window(drv.window_handles[-1])
    ready_state_complete(drv, 60)
    t0 = time.time()
    while time.time() - t0 < 75:
        if editor_ready(drv):
            return True
        time.sleep(0.5)
    return False


def open_composer(drv):
    if try_composer_url(drv):
        return
    if try_feed_then_click_write_article(drv):
        return
    debug_dump(drv, "debug_composer")
    raise TimeoutError("LinkedIn editor did not appear. See debug_composer.*")


def debug_dump(drv, stem="debug"):
    try:
        drv.save_screenshot(f"/app/data/{stem}.png")
        Path(f"/app/data/{stem}.html").write_text(drv.page_source, encoding="utf-8", errors="ignore")
        print(f"[debug] Saved /app/data/{stem}.png and .html")
    except Exception as e:
        print(f"[debug] Could not save debug artifacts: {e}")


def find_clickable(drv, xps, timeout_each=10):
    for xp in xps:
        try:
            el = WebDriverWait(drv, timeout_each).until(EC.element_to_be_clickable((By.XPATH, xp)))
            return el
        except Exception:
            pass
    return None


def ensure_modal(drv, timeout=60):
    try:
        WebDriverWait(drv, timeout).until(EC.presence_of_element_located(
            (By.XPATH, "//div[contains(@role,'dialog') or contains(@class,'artdeco-modal')]")
        ))
        return True
    except Exception:
        return False


def _find_headline_element(drv):
    input_like = [
        # LinkedIn article editor uses a textarea with id containing 'headline' and placeholder='Title'
        "//textarea[contains(@id,'article-editor-headline') or contains(@class,'article-editor-headline')]",
        "//textarea[@placeholder='Title' and @required]",
        "//input[( @placeholder or @aria-label ) and (contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'headline') or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'title') or contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'headline') or contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'title'))]",
        "//textarea[( @placeholder or @aria-label ) and (contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'headline') or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'title') or contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'headline'))]",
    ]
    editable_like = [
        "//div[@contenteditable='true' and (@data-placeholder='Add a headline' or @data-placeholder='Add headline' or contains(translate(@data-placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'title'))]",
        "//h1[@contenteditable='true']",
        "//div[@role='textbox' and @contenteditable='true' and (contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'headline') or contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'title'))]",
        "//header//*[(@contenteditable='true') or self::h1[@contenteditable='true']]",
        "(//div[@contenteditable='true'])[1]",
    ]
    for xp in input_like + editable_like:
        try:
            el = WebDriverWait(drv, 10).until(EC.element_to_be_clickable((By.XPATH, xp)))
            return el
        except Exception:
            pass
    return None


def _get_textlike_value(drv, el):
    return drv.execute_script("""
        const el = arguments[0];
        const tn = el.tagName.toLowerCase();
        if (tn === 'input' || tn === 'textarea') return el.value || '';
        if (el.getAttribute('contenteditable') === 'true') return el.innerText || el.textContent || '';
        return '';
    """, el) or ""


def _set_via_exec_command(drv, el, text):
    return drv.execute_script("""
        const el = arguments[0]; const text = arguments[1];
        el.focus();
        try { document.execCommand('selectAll', false, null); document.execCommand('delete', false, null); } catch(e){}
        const ok = document.execCommand('insertText', false, text);
        el.dispatchEvent(new InputEvent('input', {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
        return ok;
    """, el, text)


def _set_value_and_events(drv, el, text):
    return drv.execute_script("""
        const el = arguments[0]; const text = arguments[1];
        const tn = el.tagName.toLowerCase();
        el.focus();
        if (tn === 'input' || tn === 'textarea') { el.value = text; }
        else if (el.getAttribute('contenteditable') === 'true') { el.textContent = text; }
        else { return false; }
        el.dispatchEvent(new InputEvent('input', {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
        el.blur();
        return true;
    """, el, text)


def set_headline(drv, headline):
    el = _find_headline_element(drv)
    if not el:
        debug_dump(drv, "debug_headline_not_found")
        raise RuntimeError("Could not locate the headline field.")

    try:
        drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        el.click()
        time.sleep(0.2)
    except Exception:
        pass

    def ok_now():
        val  = " ".join((_get_textlike_value(drv, el) or "").split())
        want = " ".join((headline or "").split())
        return val == want

    # Strategy 1: key events
    try:
        el.send_keys(Keys.CONTROL, "a"); el.send_keys(Keys.DELETE)
        time.sleep(0.1)
        for chunk in [headline[i:i+20] for i in range(0, len(headline), 20)]:
            el.send_keys(chunk); time.sleep(0.02)
        if ok_now(): return
    except Exception:
        pass

    # Strategy 2: execCommand insertText
    try:
        _set_via_exec_command(drv, el, headline)
        time.sleep(0.15)
        if ok_now(): return
    except Exception:
        pass

    # Strategy 3: set value + dispatch events
    try:
        _set_value_and_events(drv, el, headline)
        time.sleep(0.15)
        if ok_now(): return
    except Exception:
        pass

    # Final: re-focus and type
    try:
        el.click(); time.sleep(0.1)
        el.send_keys(Keys.CONTROL, "a"); el.send_keys(Keys.DELETE)
        el.send_keys(headline); time.sleep(0.15)
        if ok_now(): return
    except Exception:
        pass

    debug_dump(drv, "debug_headline_sticky")
    raise RuntimeError("Headline could not be set.")


def set_body(drv, html_body):
    candidates = [
        "//div[@contenteditable='true' and contains(@data-placeholder,'Start writing')]",
        "//div[@role='textbox' and @contenteditable='true' and not(ancestor::header)]",
        "//div[@contenteditable='true' and not(ancestor::header)]",
        "(//div[@contenteditable='true'])[last()]",
    ]
    last_err = None
    for xp in candidates:
        try:
            body = wait(drv, 20).until(EC.element_to_be_clickable((By.XPATH, xp)))
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", body)
            body.click()
            drv.execute_script("""
                const el = arguments[0]; const html = arguments[1];
                el.focus();
                try { document.execCommand('selectAll', false, null); document.execCommand('delete', false, null); } catch(e){}
                const sel = window.getSelection();
                if (!sel.rangeCount) {
                    const r = document.createRange();
                    r.selectNodeContents(el); r.collapse(false);
                    sel.removeAllRanges(); sel.addRange(r);
                }
                const range = sel.getRangeAt(0);
                const tmp = document.createElement('div');
                tmp.innerHTML = html;
                const frag = document.createDocumentFragment();
                while (tmp.firstChild) frag.appendChild(tmp.firstChild);
                range.deleteContents();
                range.insertNode(frag);
            """, body, html_body)
            time.sleep(0.8)
            return
        except Exception as e:
            last_err = e
    debug_dump(drv, "debug_body")
    raise RuntimeError(f"Could not set body content: {last_err}")


def click_next(drv):
    next_selectors = [
        "//button[.//span[normalize-space()='Next']]",
        "//button[normalize-space()='Next']",
        "//button[contains(@aria-label,'Next')]",
        "//div[@role='dialog']//button[.//span[normalize-space()='Next']]",
    ]
    btn = find_clickable(drv, next_selectors, timeout_each=5)
    if btn:
        try:
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.2)
            drv.execute_script("arguments[0].click();", btn)
            print("[next] Clicked.")
            time.sleep(0.8)
        except Exception as e:
            print(f"[next] warning: {e}")
    else:
        print("[next] No 'Next' button visible; continuing.")


def select_newsletter_and_publish(drv, subtitle_text):
    """Open publish modal, select newsletter, fill subtitle, click final Publish."""

    def click_publish_button_on_page():
        publish_selectors = [
            "//button[.//span[normalize-space()='Publish']]",
            "//button[normalize-space()='Publish']",
            "//header//button[.//span[normalize-space()='Publish']]",
        ]
        btn = find_clickable(drv, publish_selectors, timeout_each=5)
        if btn:
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.2)
            drv.execute_script("arguments[0].click();", btn)
            print("[publish] Primary clicked (to open modal).")
            return True
        return False

    modal_present = ensure_modal(drv, timeout=4)
    if not modal_present:
        if click_publish_button_on_page():
            modal_present = ensure_modal(drv, timeout=20)
    if not modal_present:
        modal_present = ensure_modal(drv, timeout=10)
    if not modal_present:
        debug_dump(drv, "debug_publish_open")
        raise RuntimeError("Could not open the publish dialog.")

    # Prefer Newsletter destination
    try:
        click_if_visible(drv, [
            "//label[.//span[contains(.,'Newsletter')]]/preceding-sibling::input[@type='radio']",
            "//button[.//span[contains(.,'Newsletter')]]",
            "//*[contains(@role,'tab') and .//span[contains(.,'Newsletter')]]",
        ], pause=0.2)
    except Exception:
        pass

    # Choose newsletter by name
    picked = False
    try:
        cand = drv.find_elements(By.XPATH,
            f"//span[normalize-space()='{NEWSLETTER_NAME}']/ancestor::*[(self::label or self::button or self::div or self::li)][1]"
        )
        if cand:
            drv.execute_script("arguments[0].click();", cand[0])
            picked = True
    except Exception:
        pass

    if not picked:
        try:
            click_if_visible(drv, [
                "//*[@role='combobox']",
                "//button[contains(@id,'newsletter') and contains(@aria-expanded,'false')]",
            ], pause=0.3)
            time.sleep(0.4)
            opt = find_clickable(drv, [
                f"//div[@role='listbox']//div[normalize-space()='{NEWSLETTER_NAME}']",
                f"//ul[contains(@role,'listbox')]//li[.//span[normalize-space()='{NEWSLETTER_NAME}']]",
                f"//*[self::div or self::span or self::li][normalize-space()='{NEWSLETTER_NAME}']",
            ], timeout_each=5)
            if opt:
                drv.execute_script("arguments[0].click();", opt)
                picked = True
        except Exception:
            pass

    if not picked:
        print("[publish] Newsletter picker not visible or already selected; continuing.")

    # Subtitle field
    try:
        sub = drv.find_element(By.XPATH, "//textarea | //div[@role='textbox' and @contenteditable='true']")
        drv.execute_script("arguments[0].scrollIntoView({block:'center'});", sub)
        sub.click()
        for _ in range(3):
            sub.send_keys(Keys.CONTROL, "a"); sub.send_keys(Keys.DELETE)
        sub.send_keys(subtitle_text[:250])
    except Exception:
        pass

    # Final Publish inside modal
    confirm_selectors = [
        "//div[contains(@role,'dialog') or contains(@class,'artdeco-modal')]//button[.//span[normalize-space()='Publish']]",
        "//div[contains(@role,'dialog') or contains(@class,'artdeco-modal')]//button[normalize-space()='Publish']",
        "//div[contains(@role,'dialog') or contains(@class,'artdeco-modal')]//button[.//span[contains(.,'Publish now')]]",
        "//div[contains(@role,'dialog') or contains(@class,'artdeco-modal')]//button[.//span[normalize-space()='Post']]",
        "//button[@data-test-id='confirmPublish']",
    ]
    btn = find_clickable(drv, confirm_selectors, timeout_each=15)
    if not btn:
        debug_dump(drv, "debug_publish_confirm")
        raise RuntimeError("Final Publish confirm not found.")
    drv.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
    time.sleep(0.2)
    drv.execute_script("arguments[0].click();", btn)
    print("[publish] Confirmed.")


# ===================== MAIN =====================

def main():
    print(f"[build] Fetching {SOURCE_URL} …")
    r = requests.get(SOURCE_URL, timeout=30)
    r.raise_for_status()

    print("[build] Extracting content…")
    title, body_html = extract_content(r.text, SOURCE_URL)
    print(f"[build] Title: {title}")

    # Duplicate guard
    posted = load_posted()
    unique_key = f"issue:{title}"
    if unique_key in posted:
        print(f"[guard] Already posted: {title}")
        return

    drv = make_driver()
    try:
        ensure_login(drv)
        open_composer(drv)
        print("[editor] Ready. Setting headline and body…")
        set_headline(drv, title)
        set_body(drv, body_html)
        click_next(drv)

        # Re-try Next if modal hasn't appeared yet
        if not ensure_modal(drv, timeout=2):
            try:
                el = _find_headline_element(drv)
                if el and _get_textlike_value(drv, el).strip():
                    click_next(drv)
            except Exception:
                pass

        subtitle = f"Online learning news and commentary — {title}"
        select_newsletter_and_publish(drv, subtitle)

        try:
            WebDriverWait(drv, 45).until(EC.presence_of_element_located(
                (By.XPATH, "//div[contains(.,'Published') or contains(.,'published')] | //a[contains(.,'View') and contains(.,'post')]")
            ))
        except Exception:
            pass

        print("[done] Issue published.")
        posted.add(unique_key)
        save_posted(posted)

    except Exception as e:
        print(f"[fatal] {e}")
        debug_dump(drv, "debug_fatal")
        raise
    finally:
        if HEADLESS:
            drv.quit()


if __name__ == "__main__":
    main()
