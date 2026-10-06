"""Minimal Amazon web client: login (incl. 2FA) and order history scraping."""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup, Tag
import pyotp
from yarl import URL

from .parser import Order, has_next_page, parse_order_history

_LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
LANGUAGES = {
    "amazon.de": "de-DE,de;q=0.9",
    "amazon.at": "de-AT,de;q=0.9",
    "amazon.fr": "fr-FR,fr;q=0.9",
    "amazon.it": "it-IT,it;q=0.9",
    "amazon.es": "es-ES,es;q=0.9",
    "amazon.nl": "nl-NL,nl;q=0.9",
}
MAX_LOGIN_STEPS = 8


class AmazonError(Exception):
    """Base error."""


class AmazonConnectionError(AmazonError):
    """Amazon could not be reached."""


class AmazonAuthError(AmazonError):
    """Credentials were rejected."""


class AmazonMfaRequired(AmazonError):
    """A one-time password is required and no TOTP secret is configured."""


class AmazonCaptchaError(AmazonError):
    """Amazon asks for a captcha; log in once in a browser and retry later."""


class AmazonApprovalRequired(AmazonError):
    """Amazon asks to approve the login in the app / by e-mail."""


class AmazonClient:
    """Talks to the Amazon website."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        domain: str,
        email: str,
        password: str,
        otp_secret: str | None = None,
    ) -> None:
        self._session = session
        self.base_url = f"https://www.{domain}"
        self._email = email
        self._password = password
        self._otp_secret = (otp_secret or "").replace(" ", "") or None
        self._pending_form: tuple[str, dict[str, str]] | None = None
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": LANGUAGES.get(domain, "en-US,en;q=0.9"),
        }

    async def async_close(self) -> None:
        """Close the underlying HTTP session."""
        await self._session.close()

    # -- cookies -----------------------------------------------------------

    def export_cookies(self) -> dict[str, str]:
        """Return the session cookies so they can be persisted."""
        jar = self._session.cookie_jar.filter_cookies(URL(self.base_url))
        return {name: morsel.value for name, morsel in jar.items()}

    def import_cookies(self, cookies: dict[str, str]) -> None:
        """Restore persisted cookies."""
        if cookies:
            self._session.cookie_jar.update_cookies(cookies, URL(self.base_url))

    # -- http --------------------------------------------------------------

    async def _request(self, method: str, url: str, data: dict | None = None) -> tuple[str, str]:
        headers = dict(self._headers)
        if method == "POST":
            headers["Referer"] = url
            headers["Origin"] = self.base_url
        try:
            async with self._session.request(
                method, url, data=data, headers=headers, allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                if resp.status >= 500:
                    raise AmazonConnectionError(f"HTTP {resp.status} from {url}")
                return text, str(resp.url)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AmazonConnectionError(str(err)) from err

    @staticmethod
    def _is_login_page(html: str, url: str) -> bool:
        return "/ap/" in url or 'name="signIn"' in html or 'id="auth-mfa-form"' in html

    # -- login -------------------------------------------------------------

    async def async_login(self) -> None:
        """Log in, raising one of the Amazon* errors on failure."""
        self._pending_form = None
        html, url = await self._request("GET", self._orders_url(0))
        await self._process_login(html, url)

    async def async_submit_otp(self, code: str) -> None:
        """Submit a one-time password after AmazonMfaRequired was raised."""
        if not self._pending_form:
            raise AmazonAuthError("No pending 2FA request")
        action, fields = self._pending_form
        self._pending_form = None
        fields["otpCode"] = code.strip()
        html, url = await self._request("POST", action, fields)
        await self._process_login(html, url, password_sent=True)

    async def _process_login(self, html: str, url: str, password_sent: bool = False) -> None:
        for _ in range(MAX_LOGIN_STEPS):
            if not self._is_login_page(html, url):
                _LOGGER.debug("Amazon login successful")
                return

            soup = BeautifulSoup(html, "html.parser")

            if (
                soup.find(id="auth-captcha-image")
                or soup.find("input", attrs={"name": "captchacharacters"})
                or soup.find(id="aacb-captcha-header")
                or "validateCaptcha" in html
            ):
                raise AmazonCaptchaError("Amazon verlangt ein Captcha")

            if soup.find(id="resend-approval-link") or "transactionApprovalStatus" in html:
                raise AmazonApprovalRequired("Login muss in der Amazon-App bestätigt werden")

            if skip := soup.select_one("#ap-account-fixup-phone-skip-link, a[id*='skip-link']"):
                html, url = await self._request("GET", urljoin(url, skip.get("href", "")))
                continue

            mfa_form = soup.find("form", id="auth-mfa-form") or _form_with_input(soup, "otpCode")
            if mfa_form:
                action, fields = _form_data(mfa_form, url)
                fields["rememberDevice"] = "true"
                if not self._otp_secret:
                    self._pending_form = (action, fields)
                    raise AmazonMfaRequired("Bestätigungscode erforderlich")
                fields["otpCode"] = pyotp.TOTP(self._otp_secret).now()
                html, url = await self._request("POST", action, fields)
                continue

            device_form = soup.find("form", id="auth-select-device-form") or soup.find("form", attrs={"name": "claimspicker"})
            if device_form:
                action, fields = _form_data(device_form, url)
                html, url = await self._request("POST", action, fields)
                continue

            sign_in = soup.find("form", attrs={"name": "signIn"})
            if sign_in is None:
                raise AmazonAuthError("Unbekannte Login-Seite")

            if password_sent and soup.select_one("#auth-error-message-box, #auth-warning-message-box .a-alert-content"):
                raise AmazonAuthError("Amazon hat die Zugangsdaten abgelehnt")

            action, fields = _form_data(sign_in, url)
            if "email" in fields or sign_in.find("input", attrs={"name": "email"}):
                fields["email"] = self._email
            if sign_in.find("input", attrs={"name": "password"}):
                fields["password"] = self._password
                fields["rememberMe"] = "true"
                password_sent = True
            html, url = await self._request("POST", action, fields)

        raise AmazonAuthError("Login nach zu vielen Schritten abgebrochen")

    # -- orders ------------------------------------------------------------

    def _orders_url(self, page: int) -> str:
        return f"{self.base_url}/your-orders/orders?timeFilter=months-3&startIndex={page * 10}"

    async def async_get_orders(self, max_pages: int) -> list[Order]:
        """Fetch the order history (logging in when necessary)."""
        orders: list[Order] = []
        for page in range(max_pages):
            html, url = await self._request("GET", self._orders_url(page))
            if self._is_login_page(html, url):
                await self.async_login()
                html, url = await self._request("GET", self._orders_url(page))
                if self._is_login_page(html, url):
                    raise AmazonAuthError("Nach dem Login weiterhin nicht angemeldet")
            orders.extend(parse_order_history(html, self.base_url))
            if not has_next_page(html):
                break
        return orders


def _form_with_input(soup: BeautifulSoup, name: str) -> Tag | None:
    field = soup.find("input", attrs={"name": name})
    return field.find_parent("form") if field else None


def _form_data(form: Tag, page_url: str) -> tuple[str, dict[str, str]]:
    action = urljoin(page_url, form.get("action") or page_url)
    fields: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        if inp.get("type") in ("checkbox", "radio") and not inp.has_attr("checked"):
            if inp.get("type") == "radio" and name not in fields:
                fields[name] = inp.get("value", "")  # fall back to first option
            continue
        fields[name] = inp.get("value", "")
    return action, fields
