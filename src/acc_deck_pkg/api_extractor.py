#!/usr/bin/env python3
"""
api_extractor.py
NPD External API — Industry Discovery & Data Extraction

Cloned from dashboard_download_foodservice/Code/api_extractor_v2.py for use
within the ADB acc_deck_pkg package.  The only difference is that cookie files
are stored under the ADB project root (parent of acc_deck_pkg/) rather than
the dashboard_download_foodservice directory.

Flow:
  1. connect(username, password, env_key)  → requests.Session
  2. fetch_industries(session)             → [{id, label}, ...]
  3. get_industry_forecast(session, env_key, industry_id) → pd.DataFrame

Endpoints:
  GET .../api/ext/industries                          — list all available industries
  GET .../api/ext/industry/{id}/forecast?timeGran=... — quarterly forecast data

Base URLs are read from environment variables NPD_PROD_URL and NPD_QA_URL.
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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Selenium is only needed for _selenium_login(); imported lazily so the module
# can be imported even if selenium is not installed in the current environment.


# ============================================================================
# CONFIGURATION
# ============================================================================

def _get_environments() -> dict:
    prod = os.getenv("NPD_PROD_URL", "")
    qa   = os.getenv("NPD_QA_URL", "")
    return {
        'prod': {
            'name': 'Production',
            'login_url': f'{prod}/login?destination=/',
            'base_url': f'{prod}/data-navigator/future-of-admin',
            'domain': prod.replace('https://', ''),
            'referer': f'{prod}/data-navigator/',
            'origin': prod,
            'verify_ssl': True,
            'output_name': 'forecast',
        },
        'qa': {
            'name': 'QA',
            'login_url': f'{qa}/login?destination=node/934',
            'base_url': f'{qa}/data-navigator/future-of-admin',
            'domain': qa.replace('https://', ''),
            'referer': f'{qa}/data-navigator/',
            'origin': qa,
            'verify_ssl': False,
            'output_name': 'actuals',
        },
    }

# Keep ENVIRONMENTS as a module-level alias for backwards compatibility,
# but always resolve fresh via _get_environments() at call time.
ENVIRONMENTS = _get_environments()

COOKIE_EXPIRY_MINUTES = 50

_API_PATH_INDUSTRIES = os.getenv("NPD_API_PATH_INDUSTRIES", "/api/ext/industries")
_API_PATH_FORECAST   = os.getenv("NPD_API_PATH_FORECAST",   "/api/ext/industry/{id}/forecast")


# ============================================================================
# COOKIE PERSISTENCE
# ============================================================================

def _writable_base() -> Path:
    """
    Return a writable base directory that works both in dev and when frozen
    by PyInstaller.

    - Frozen (.exe):  directory containing the executable
    - Dev (source):   ADB project root (one level above acc_deck_pkg/)
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
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import TimeoutException

    env = _get_environments()[env_key]
    print(f"\n  Logging in to {env['name']}...")
    print(f"  Login URL: {env['login_url']}")

    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-images')
    chrome_options.add_argument('--blink-settings=imagesEnabled=false')
    chrome_options.add_argument('--disk-cache-size=0')
    chrome_options.add_argument('--media-cache-size=0')

    # Docker / Linux: Chromium binary may be at a non-standard path.
    # Set CHROME_BIN env var to override (e.g. /usr/bin/chromium).
    chrome_bin = os.environ.get('CHROME_BIN', '')
    if chrome_bin:
        chrome_options.binary_location = chrome_bin

    from selenium.webdriver.chrome.service import Service as _ChromeService
    chromedriver_path = os.environ.get('CHROMEDRIVER_PATH', '')
    service = _ChromeService(executable_path=chromedriver_path) if chromedriver_path else _ChromeService()
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        print(f"  Opening login page...")
        driver.get(env['login_url'])

        print(f"  Clicking SSO login button...")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "edit-openid-connect-client-generic-login"))
        ).click()
        time.sleep(2)  # wait for Microsoft login page to load

        print(f"  Entering username ({username})...")
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "rawUserInput"))
        ).send_keys(username)

        print(f"  Submitting username...")
        WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "continue"))
        ).click()
        time.sleep(4)  # wait for password page to load

        print(f"  Entering password...")
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "i0118"))
        ).send_keys(password)

        print(f"  Submitting credentials...")
        WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "idSIButton9"))
        ).click()

        # Handle "Stay signed in?" prompt
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "idSIButton9"))
            ).click()
            print(f"  Dismissed 'Stay signed in?' prompt")
        except TimeoutException:
            pass

        print(f"  Waiting for SSO redirect back to {env['name']}...")
        try:
            WebDriverWait(driver, 40).until(
                lambda d: env['domain'] in d.current_url and "microsoft" not in d.current_url
            )
        except TimeoutException:
            print(f"  Redirect timed out — current URL: {driver.current_url}")
            raise

        cookies = driver.get_cookies()
        cookie_names = [c['name'] for c in cookies]
        print(f"  Login successful — {len(cookies)} cookies received ({', '.join(cookie_names)})")

        if 'datanav_auth' not in cookie_names:
            print(f"  WARNING: datanav_auth not found — API requests will likely fail")

        return cookies

    except Exception as e:
        import traceback
        print(f"  Login failed: {e}")
        print(traceback.format_exc())
        return None
    finally:
        driver.quit()


def _build_session(cookies: list, env_key: str) -> requests.Session:
    """Apply a cookie jar to a new requests Session."""
    env = _get_environments()[env_key]
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
# ============================================================================

def connect(username: str, password: str, env_key: str) -> Optional[requests.Session]:
    """
    Authenticate to an NPD environment, reusing cached cookies if still valid.

    Args:
        username: NPD login username.
        password: NPD login password.
        env_key:  'prod' or 'qa'.

    Returns:
        An authenticated requests.Session, or None if login failed.
    """
    env = _get_environments()[env_key]
    print(f"\n  Connecting to {env['name']}...")

    cookies = _load_cookies(env_key)

    if cookies is None:
        print(f"  No valid cached cookies — running Selenium SSO login...")
        cookies = _selenium_login(username, password, env_key)
        if not cookies:
            return None
        _save_cookies(cookies, env_key)
    else:
        print(f"  Using cached cookies")

    return _build_session(cookies, env_key)


# ============================================================================
# STEP 2: fetch_industries  —  requires an authenticated prod session
# ============================================================================

def fetch_industries(session: requests.Session) -> list:
    """
    Fetch the list of available industries using an authenticated prod session.

    Returns:
        List of dicts with 'id' and 'label' keys, filtered to hasForecasts=True.
    """
    url = f"{_get_environments()['prod']['base_url']}{_API_PATH_INDUSTRIES}"
    print(f"\n  GET {url}")

    response = session.get(url, timeout=(10, 30))
    print(f"  HTTP {response.status_code}")
    response.raise_for_status()

    content_type = response.headers.get('Content-Type', '')
    if 'application/json' not in content_type:
        raise ValueError(
            f"Expected JSON from industries endpoint but got '{content_type}'. "
            f"Session may have expired — delete Cookies/*.pkl and reconnect."
        )

    df = pd.DataFrame(response.json())
    df_filtered = df[df['hasForecasts'] == True].copy()
    print(f"  {len(df_filtered)} industries with forecasts available")
    return df_filtered[['id', 'label']].to_dict('records')


# ============================================================================
# STEP 3: get_industry_forecast  —  requires an authenticated session
# ============================================================================

def get_industry_forecast(
    session: requests.Session,
    env_key: str,
    industry_id: str,
    time_gran: str = 'yyyyq',
    level: str = None,
) -> pd.DataFrame:
    """Fetch quarterly forecast data for one industry from one environment."""
    url = f"{_get_environments()[env_key]['base_url']}{_API_PATH_FORECAST.replace('{id}', str(industry_id))}"
    params = {'timeGran': time_gran}
    if level is not None:
        params['level'] = level

    print(f"\n  GET {url}")
    print(f"  Params: {params}")

    response = session.get(url, params=params, timeout=60)
    print(f"  HTTP {response.status_code}")
    response.raise_for_status()

    data = response.json()

    all_tables = []
    for wave in data:
        df = pd.DataFrame(wave['table'])
        df['wave'] = wave.get('wave')
        df['label'] = wave.get('label')
        df['filter'] = wave.get('filter')
        all_tables.append(df)

    return pd.concat(all_tables, ignore_index=True)
