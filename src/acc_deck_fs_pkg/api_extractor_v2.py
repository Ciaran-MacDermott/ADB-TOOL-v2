#!/usr/bin/env python3
"""
api_extractor_v2.py
NPD External API — Industry Discovery & Data Extraction

Flow:
  1. connect(username, password, env_key)  → requests.Session
  2. fetch_industries(session)             → [{id, label}, ...]
  3. extract_data(prod_session, qa_session, industry_id, output_dir)

Login (Selenium SSO) is always step 1. Sessions are passed through to
subsequent API calls so login only happens once per environment.

Endpoints:
  GET /api/ext/industries                          — list all available industries
  GET /api/ext/industry/{id}/forecast?timeGran=... — forecast data for a specific industry

Production:  https://future-of.npd.com/data-navigator/future-of-admin
QA:          https://future-of-qa.npd.com/data-navigator/future-of-admin

──────────────────────────────────────────────────────────────────────────
NETWORK POLICY — egress (foodservice pipeline)
──────────────────────────────────────────────────────────────────────────
Same hosts as acc_deck_pkg.api_extractor:
  - future-of.npd.com:443       (prod, default)  — env: NPD_PROD_URL
  - future-of-qa.npd.com:443    (QA,   default)  — env: NPD_QA_URL

Note: src/acc_deck_fs_pkg/Templates/template.pptx is currently a Git LFS
pointer (~131 bytes). The pipeline cannot generate decks without the
real binary. Either install git-lfs and pull, or commit the binary
directly out of LFS, before deploying into a walled-garden CI that
lacks LFS access.
"""

import os
import sys
import time
import pickle
import requests
import pandas as pd
import urllib3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================================
# CONFIGURATION
# ============================================================================

# URLs read from env vars to stay aligned with acc_deck_pkg/api_extractor.py.
# Both PROD and QA base URLs must include the /data-navigator/future-of-admin
# path prefix — the API endpoints are mounted there in both environments.
def _get_environments() -> dict:
    prod = os.getenv("NPD_PROD_URL", "https://future-of.npd.com")
    qa   = os.getenv("NPD_QA_URL",   "https://future-of-qa.npd.com")
    return {
        'prod': {
            'name': 'Production',
            'login_url': f'{prod}/login?destination=/',
            'base_url':  f'{prod}/data-navigator/future-of-admin',
            'domain':    prod.replace('https://', ''),
            'referer':   f'{prod}/data-navigator/',
            'origin':    prod,
            'verify_ssl': True,
            'output_name': 'forecast',
            'cookie_file': '../Cookies/npd_cookies_prod.pkl',
        },
        'qa': {
            'name': 'QA',
            'login_url': f'{qa}/login?destination=node/934',
            'base_url':  f'{qa}/data-navigator/future-of-admin',
            'domain':    qa.replace('https://', ''),
            'referer':   f'{qa}/data-navigator/',
            'origin':    qa,
            'verify_ssl': False,
            'output_name': 'actuals',
            'cookie_file': '../Cookies/npd_cookies_qa.pkl',
        },
    }

ENVIRONMENTS = _get_environments()

COOKIE_EXPIRY_MINUTES = 50


# ============================================================================
# COOKIE PERSISTENCE
# ============================================================================

def _writable_base() -> Path:
    """
    Return a writable base directory that works both in dev and when frozen
    by PyInstaller.

    - Frozen (.exe):  directory containing the executable
    - Dev (source):   dashboard_download_foodservice/ (two levels up from Code/)
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _cookie_path(env_key: str) -> Path:
    path = _writable_base() / "Cookies" / f"npd_cookies_{env_key}.pkl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _save_cookies(cookies: list, env_key: str):
    data = {
        'cookies': cookies,
        'expires': datetime.now() + timedelta(minutes=COOKIE_EXPIRY_MINUTES),
    }
    with open(_cookie_path(env_key), 'wb') as f:
        pickle.dump(data, f)
    print(f"  Cookies saved (valid for {COOKIE_EXPIRY_MINUTES} minutes)")


def _load_cookies(env_key: str) -> Optional[list]:
    path = _cookie_path(env_key)
    if not path.exists():
        return None
    try:
        with open(path, 'rb') as f:
            data = pickle.load(f)
        if datetime.now() > data['expires']:
            print(f"  Saved cookies expired — Selenium login required")
            return None
        remaining = int((data['expires'] - datetime.now()).total_seconds() / 60)
        print(f"  Loaded cookies from file ({remaining} min remaining)")
        return data['cookies']
    except Exception as e:
        print(f"  Could not load cookies: {e}")
        return None


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _selenium_login(username: str, password: str, env_key: str) -> Optional[list]:
    """Run Selenium SSO login. Returns raw cookie list or None on failure."""
    env = ENVIRONMENTS[env_key]
    print(f"\n  Logging in to {env['name']}...")

    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get(env['login_url'])
        time.sleep(2)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "edit-openid-connect-client-generic-login"))
        ).click()
        time.sleep(3)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "rawUserInput"))
        ).send_keys(username)

        WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "continue"))
        ).click()
        time.sleep(5)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "i0118"))
        ).send_keys(password)

        WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "idSIButton9"))
        ).click()

        # Handle "Stay signed in?" prompt
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "idSIButton9"))
            ).click()
        except TimeoutException:
            pass

        time.sleep(5)
        WebDriverWait(driver, 20).until(
            lambda d: env['domain'] in d.current_url and "microsoft" not in d.current_url
        )

        cookies = driver.get_cookies()
        cookie_names = [c['name'] for c in cookies]
        print(f"  Login successful — cookies: {cookie_names}")

        if 'datanav_auth' not in cookie_names:
            print(f"  WARNING: datanav_auth not found — API requests will likely fail")

        return cookies

    except Exception as e:
        print(f"  Login failed: {e}")
        return None
    finally:
        driver.quit()


def _build_session(cookies: list, env_key: str) -> requests.Session:
    """Apply a cookie jar to a new requests Session."""
    env = ENVIRONMENTS[env_key]
    session = requests.Session()
    session.verify = env['verify_ssl']

    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Referer': env['referer'],
        'Origin': env['origin'],
    })

    for cookie in cookies:
        session.cookies.set(
            cookie['name'],
            cookie['value'],
            domain=cookie.get('domain'),
            path=cookie.get('path'),
        )

    return session


# ============================================================================
# STEP 1: connect  —  login via Selenium, return an authenticated session
# This is always the first call. The returned session is passed to all
# subsequent API calls so login only happens once per environment.
# ============================================================================

def connect(username: str, password: str, env_key: str) -> Optional[requests.Session]:
    """
    Authenticate to an NPD environment, reusing cached cookies if still valid.

    Checks for a saved cookie pickle first. If found and not expired, Selenium
    is skipped entirely. Otherwise runs Selenium SSO and saves new cookies.

    Args:
        username: NPD login username.
        password: NPD login password.
        env_key:  'prod' or 'qa'.

    Returns:
        An authenticated requests.Session, or None if login failed.
    """
    env = ENVIRONMENTS[env_key]
    print(f"\n  Connecting to {env['name']}...")

    # Try cached cookies first
    cookies = _load_cookies(env_key)

    if cookies is None:
        # No valid cache — run Selenium login and persist the new cookies
        cookies = _selenium_login(username, password, env_key)
        if not cookies:
            return None
        _save_cookies(cookies, env_key)

    return _build_session(cookies, env_key)


# ============================================================================
# STEP 2: fetch_industries  —  requires an authenticated prod session
# ============================================================================

def fetch_industries(session: requests.Session) -> list:
    """
    Fetch the list of available industries using an authenticated prod session.

    Args:
        session: Authenticated requests.Session from connect(username, password, 'prod').

    Returns:
        List of dicts with 'id' and 'label' keys, filtered to hasForecasts=True.
        Empty list if the API call fails.
    """
    url = f"{ENVIRONMENTS['prod']['base_url']}/api/ext/industries"
    print(f"\n  GET {url}")

    response = session.get(url, timeout=30)
    print(f"  HTTP {response.status_code}")
    print(f"  Content-Type: {response.headers.get('Content-Type', 'unknown')}")

    if not response.ok:
        print(f"  Response body: {response.text[:300]}")
        response.raise_for_status()

    try:
        payload = response.json()
    except Exception as json_err:
        print(f"  Failed to parse JSON: {json_err}")
        print(f"  Raw response (first 300 chars): {response.text[:300]}")
        raise

    print(f"  Payload type: {type(payload).__name__}, length: {len(payload) if isinstance(payload, (list, dict)) else 'n/a'}")

    df = pd.DataFrame(payload)
    print(f"  Columns: {list(df.columns)}")

    if 'hasForecasts' not in df.columns:
        print(f"  WARNING: 'hasForecasts' column not found — returning all {len(df)} industries")
        return df[['id', 'label']].to_dict('records')

    df_filtered = df[df['hasForecasts'].astype(bool)].copy()
    print(f"  {len(df_filtered)} / {len(df)} industries with forecasts available")
    return df_filtered[['id', 'label']].to_dict('records')


# ============================================================================
# STEP 3: extract_data  —  requires authenticated prod + qa sessions
# ============================================================================

def get_industry_forecast(session: requests.Session, env_key: str,
                          industry_id: str, time_gran: str = 'yyyyq',
                          level: str = None) -> pd.DataFrame:
    """Fetch quarterly forecast data for one industry from one environment."""
    url = f"{ENVIRONMENTS[env_key]['base_url']}/api/ext/industry/{industry_id}/forecast"
    params = {'timeGran': time_gran}
    if level is not None:
        params['level'] = level

    print(f"\n  GET {url}")
    print(f"  Params: {params}")

    response = session.get(url, params=params, timeout=60)
    print(f"  HTTP {response.status_code}")
    response.raise_for_status()

    data = response.json()

    # API now returns a list of wave objects, each with a 'table' key
    all_tables = []
    for wave in data:
        df = pd.DataFrame(wave['table'])
        df['wave'] = wave.get('wave')
        df['label'] = wave.get('label')
        df['filter'] = wave.get('filter')
        all_tables.append(df)

    return pd.concat(all_tables, ignore_index=True)


def extract_data(prod_session: requests.Session, qa_session: requests.Session,
                 industry_id: str, output_dir: str = None) -> dict:
    """
    Fetch forecast (prod) and actuals (qa) for an industry and save as CSVs.

    Sessions must be pre-authenticated via connect(). No Selenium login is
    performed here.

    Args:
        prod_session: Authenticated session for Production.
        qa_session:   Authenticated session for QA.
        industry_id:  Industry ID (e.g. 'food-service', 'food-service-uk').
        output_dir:   Directory to resolve the CSV save path from (default: script dir).

    Returns:
        Dict with keys 'prod' and 'qa', each mapping to a DataFrame (or None on failure).
    """
    out = Path(output_dir) if output_dir else Path(__file__).parent
    save_dir = (out / "../Dashboard API data").resolve()
    save_dir.mkdir(parents=True, exist_ok=True)

    sessions = {'prod': prod_session, 'qa': qa_session}
    dataframes = {}

    for env_key, session in sessions.items():
        env = ENVIRONMENTS[env_key]
        try:
            print(f"\n  Fetching quarterly data for '{industry_id}' from {env['name']}...")
            df = get_industry_forecast(session, env_key, industry_id=industry_id,
                                       time_gran='yyyyq')
            print(f"  Retrieved {len(df)} rows")

            # Add project column so downstream data_analysis.py can group/merge on it
            df['project'] = industry_id

            output_file = save_dir / f"{env['output_name']}_full.csv"
            df.to_csv(str(output_file), index=False)
            print(f"  Saved to {output_file}")

            dataframes[env_key] = df

        except Exception as e:
            print(f"  Error fetching data from {env['name']}: {e}")
            dataframes[env_key] = None

    return dataframes


# ============================================================================
# MAIN (interactive test / CLI)
# ============================================================================

def main():
    print("\n" + "=" * 60)
    print("NPD INDUSTRY DISCOVERY")
    print("=" * 60)

    print("\nEnter your NPD credentials:")
    username = input("  Username: ")
    password = input("  Password: ")

    # Step 1: Login
    print(f"\n{'─' * 60}")
    session = connect(username, password, 'prod')
    if not session:
        print("  Aborting — could not establish session.")
        return

    # Step 2: List industries
    print(f"\n{'─' * 60}")
    print("  Fetching available industries...")
    try:
        industries = fetch_industries(session)
        print(f"\n  {'id':<30} {'label'}")
        print(f"  {'─'*30} {'─'*30}")
        for item in industries:
            print(f"  {item['id']:<30} {item['label']}")
    except Exception as e:
        print(f"  Could not fetch industry list: {e}")

    print(f"\n{'=' * 60}\n")


if __name__ == "__main__":
    main()
