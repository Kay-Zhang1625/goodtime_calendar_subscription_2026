"""
spider_goodtime.py — Selenium access to goodtime.17fit.com.

login()             : username -> next -> password -> login, wait for redirect
fetch_pass_ledger() : Account -> Profile -> Passes, expand every active pass's
                      "Details" table and parse booking / cancellation rows
                      (see ledger.py).  The User (name) column is never read.

Site-specific selectors live in the SELECTORS block below; verify them
against the live page (e.g. with a browser MCP) whenever the site changes.
"""

import os
import re

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ledger import make_entry, parse_txn_datetime

USERNAME = os.environ.get("CRAWLER_USERNAME")
PASSWORD = os.environ.get("CRAWLER_PASSWORD")

LOGIN_URL = (
    "https://17fit.com/account/login?show_fb=1&show_line=1&show_17fit=1"
    "&success_url=https%3A%2F%2Fgoodtime.17fit.com%2Fauthorization%2Fjwt%3Fsuccess_url%3D"
    "https%3A%2F%2Fgoodtime.17fit.com%2Fstudios%3FopenExternalBrowser%3D1"
    "&fail_url=https%3A%2F%2Fgoodtime.17fit.com%2Fstudios%3FopenExternalBrowser%3D1"
    "&cancel_url=https%3A%2F%2Fgoodtime.17fit.com%2Fstudios%3FopenExternalBrowser%3D1"
)

# ---- SELECTORS: verify against the live Passes page ------------------------
PASSES_URL = "https://goodtime.17fit.com/my-account/membership"   # or None to navigate by clicking
ACCOUNT_LINK_XPATH = "//a[contains(., 'Account') or contains(., '帳戶') or contains(., '帳號')]"
PASSES_TAB_XPATH = "//a[contains(., 'Passes') or contains(., '方案')] | //button[contains(., 'Passes') or contains(., '方案')]"
ACTIVE_TAB_XPATH = "//*[self::a or self::li or self::button][contains(., '有效方案')]"
DETAILS_TOGGLE_XPATH = "//a[contains(., 'Details')] | //button[contains(., 'Details')]"
LEDGER_TABLE_CSS = "table"          # tables whose header row contains 'Reason' are used
NEXT_PAGE_XPATH = None              # e.g. "//ul[@class='pagination']//a[contains(., '›')]"; None = no pagination
MAX_PAGES = 50
# ---------------------------------------------------------------------------

HEADER_ALIASES = {
    "date": {"date", "日期", "時間"},
    "reason": {"reason", "原因", "說明"},
    "change": {"change", "變動", "異動", "點數"},
}


def create_driver():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,2000")
    return webdriver.Chrome(options=opts)


def login(wd, username, password, login_url=LOGIN_URL, timeout=15):
    if not username or not password:
        raise RuntimeError("缺少 CRAWLER_USERNAME / CRAWLER_PASSWORD 環境變數。")
    wait = WebDriverWait(wd, timeout)
    wd.get(login_url)

    username_input = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input.st-mb-0.st-text-black.st-p-3.st-w-full")))
    username_input.send_keys(username)
    wd.find_element(By.TAG_NAME, "button").click()

    password_input = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, 'input[type="password"].st-mb-0.st-text-black.st-p-3.st-w-full')))
    password_input.send_keys(password)
    wd.find_element(By.TAG_NAME, "button").click()

    try:
        wait.until(lambda d: "account/login" not in d.current_url)
    except TimeoutException as exc:
        raise RuntimeError("登入失敗：仍停留在登入頁，請檢查帳密。") from exc


def open_passes_page(wd, timeout=15):
    """Land on the Passes tab with 有效方案 selected."""
    wait = WebDriverWait(wd, timeout)
    if PASSES_URL:
        wd.get(PASSES_URL)
    else:
        wait.until(EC.element_to_be_clickable((By.XPATH, ACCOUNT_LINK_XPATH))).click()
        wait.until(EC.element_to_be_clickable((By.XPATH, PASSES_TAB_XPATH))).click()
    # make sure the active-pass list is the one displayed (it is the default tab)
    for el in wd.find_elements(By.XPATH, ACTIVE_TAB_XPATH):
        try:
            el.click()
            break
        except Exception:
            continue
    wait.until(EC.presence_of_element_located((By.XPATH, DETAILS_TOGGLE_XPATH)))


def expand_all_details(wd, timeout=10):
    """Click every collapsed 'Details' toggle; return how many toggles exist."""
    toggles = wd.find_elements(By.XPATH, DETAILS_TOGGLE_XPATH)
    for t in toggles:
        try:
            if t.is_displayed():
                wd.execute_script("arguments[0].scrollIntoView({block: 'center'});", t)
                t.click()
        except Exception:
            continue
    if toggles:
        WebDriverWait(wd, timeout).until(
            lambda d: any(_is_ledger_table(tb) for tb in BeautifulSoup(d.page_source, "html.parser").select(LEDGER_TABLE_CSS)))
    return len(toggles)


def _header_map(table):
    """Map logical column -> index using header text, ignoring the User column."""
    header_cells = table.select("thead th") or table.select("thead td")
    if not header_cells:
        first = table.find("tr")
        header_cells = first.find_all(["th", "td"]) if first else []
    mapping = {}
    for i, cell in enumerate(header_cells):
        text = cell.get_text(" ", strip=True).lower()
        for logical, aliases in HEADER_ALIASES.items():
            if logical not in mapping and any(a in text for a in aliases):
                mapping[logical] = i
    return mapping


def _is_ledger_table(table):
    m = _header_map(table)
    return "date" in m and "reason" in m


def parse_ledger_tables(html, since=None):
    """
    Parse every ledger table in `html`.  Returns (entries, n_tables, oldest_txn).
    Rows older than `since` are dropped (and the caller can stop paging).
    """
    soup = BeautifulSoup(html, "html.parser")
    entries, n_tables, oldest = [], 0, None
    skipped = 0
    for table in soup.select(LEDGER_TABLE_CSS):
        cols = _header_map(table)
        if "date" not in cols or "reason" not in cols:
            continue
        n_tables += 1
        body_rows = table.select("tbody tr") or table.find_all("tr")[1:]
        for tr in body_rows:
            tds = tr.find_all("td")
            if len(tds) <= max(cols.values()):
                continue
            date_text = tds[cols["date"]].get_text(" ", strip=True)
            reason_text = tds[cols["reason"]].get_text(" ", strip=True)
            change_text = tds[cols["change"]].get_text(" ", strip=True) if "change" in cols else ""
            try:
                txn = parse_txn_datetime(date_text)
            except ValueError:
                continue                                  # not a transaction row
            if oldest is None or txn < oldest:
                oldest = txn                              # every dated row counts for paging
            e = make_entry(date_text, reason_text, change_text, source="passes")
            if e is None:                             # not 預約課程 / 取消課程: never stored or echoed
                skipped += 1
                continue
            if since and txn < since:
                continue
            entries.append(e)
    if skipped:
        print(f"略過非預約/取消紀錄 ×{skipped}")
    return entries, n_tables, oldest


def fetch_pass_ledger(wd, since=None):
    """
    Scrape book/cancel rows from all active passes.
    Returns (entries, passes_found).  With `since`, stops paging once every
    row on a page is older than the cursor; rows equal to `since` are kept
    (the caller de-duplicates them).
    """
    open_passes_page(wd)
    passes_found = expand_all_details(wd)

    all_entries = []
    for page in range(1, MAX_PAGES + 1):
        entries, n_tables, oldest = parse_ledger_tables(wd.page_source, since=since)
        all_entries.extend(entries)
        passes_found = max(passes_found, n_tables)
        if not NEXT_PAGE_XPATH:
            break
        if since and oldest and oldest < since:
            break
        try:
            nxt = wd.find_element(By.XPATH, NEXT_PAGE_XPATH)
        except NoSuchElementException:
            break
        if not nxt.is_enabled() or "disabled" in (nxt.get_attribute("class") or ""):
            break
        nxt.click()
        WebDriverWait(wd, 10).until(EC.staleness_of(nxt))
    return all_entries, passes_found
