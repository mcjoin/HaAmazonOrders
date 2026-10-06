"""Config flow for Amazon Bestellungen."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import create_client
from .api import (
    AmazonApprovalRequired,
    AmazonAuthError,
    AmazonCaptchaError,
    AmazonClient,
    AmazonConnectionError,
    AmazonMfaRequired,
)
from .const import (
    AMAZON_DOMAINS,
    CONF_DOMAIN,
    CONF_MAX_PAGES,
    CONF_OTP_SECRET,
    CONF_RETENTION_DAYS,
    CONF_SCAN_INTERVAL,
    DEFAULT_DOMAIN,
    DEFAULT_MAX_PAGES,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONF_OTP_CODE = "otp_code"
PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class AmazonBestellungenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._client: AmazonClient | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return AmazonOptionsFlow()

    async def _async_try_login(self, otp_code: str | None = None) -> str | None:
        """Log in (or submit the OTP). Returns an error key or None on success."""
        try:
            if otp_code is not None and self._client is not None:
                await self._client.async_submit_otp(otp_code)
            else:
                await self._async_close_client()
                self._client = create_client(self.hass, self._data)
                await self._client.async_login()
        except AmazonMfaRequired:
            return "mfa"
        except AmazonCaptchaError:
            return "captcha"
        except AmazonApprovalRequired:
            return "approval"
        except AmazonAuthError:
            return "invalid_auth"
        except AmazonConnectionError:
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during Amazon login")
            return "unknown"
        return None

    async def _async_close_client(self) -> None:
        if self._client is not None:
            await self._client.async_close()
            self._client = None

    async def _async_finish(self) -> ConfigFlowResult:
        assert self._client is not None
        data = {**self._data, "cookies": self._client.export_cookies(), "cookies_ts": time.time()}
        await self._async_close_client()
        if self.source == "reauth":
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        return self.async_create_entry(
            title=f"Amazon ({data[CONF_EMAIL]}, {data[CONF_DOMAIN]})", data=data
        )

    async def _async_handle_login(self, step_id: str, schema: vol.Schema) -> ConfigFlowResult:
        error = await self._async_try_login()
        if error == "mfa":
            return await self.async_step_otp()
        if error is None:
            return await self._async_finish()
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors={"base": error},
            description_placeholders={"email": self._data.get(CONF_EMAIL, "")},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the credentials."""
        schema = vol.Schema(
            {
                vol.Required(CONF_DOMAIN, default=DEFAULT_DOMAIN): SelectSelector(
                    SelectSelectorConfig(options=AMAZON_DOMAINS, custom_value=True)
                ),
                vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
                vol.Required(CONF_PASSWORD): PASSWORD,
                vol.Optional(CONF_OTP_SECRET): PASSWORD,
            }
        )
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)

        user_input[CONF_DOMAIN] = user_input[CONF_DOMAIN].removeprefix("www.").strip()
        await self.async_set_unique_id(f"{user_input[CONF_DOMAIN]}_{user_input[CONF_EMAIL].lower()}")
        self._abort_if_unique_id_configured()
        self._data = user_input
        return await self._async_handle_login(
            "user", self.add_suggested_values_to_schema(schema, user_input)
        )

    async def async_step_otp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the one-time password (SMS / authenticator app)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._async_try_login(user_input[CONF_OTP_CODE])
            if error is None:
                return await self._async_finish()
            if error == "mfa":
                error = "invalid_otp"
            elif error == "invalid_auth":
                # The pending form is gone, start the login again for a new code.
                error = await self._async_try_login()
                if error == "mfa":
                    error = "invalid_otp"
            errors["base"] = error
        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema({vol.Required(CONF_OTP_CODE): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start re-authentication."""
        self._data = dict(entry_data)
        self._data.pop("cookies", None)
        self._data.pop("cookies_ts", None)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again."""
        schema = vol.Schema(
            {
                vol.Required(CONF_PASSWORD): PASSWORD,
                vol.Optional(CONF_OTP_SECRET): PASSWORD,
            }
        )
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=schema,
                description_placeholders={"email": self._data[CONF_EMAIL]},
            )
        self._data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
        self._data[CONF_OTP_SECRET] = user_input.get(CONF_OTP_SECRET) or self._data.get(CONF_OTP_SECRET)
        return await self._async_handle_login("reauth_confirm", schema)


class AmazonOptionsFlow(OptionsFlow):
    """Options: retention, polling interval, pages."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={k: int(v) for k, v in user_input.items()})

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RETENTION_DAYS, default=opts.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)
                ): NumberSelector(NumberSelectorConfig(min=0, max=90, mode=NumberSelectorMode.BOX, unit_of_measurement="d")),
                vol.Required(
                    CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): NumberSelector(NumberSelectorConfig(min=10, max=1440, mode=NumberSelectorMode.BOX, unit_of_measurement="min")),
                vol.Required(
                    CONF_MAX_PAGES, default=opts.get(CONF_MAX_PAGES, DEFAULT_MAX_PAGES)
                ): NumberSelector(NumberSelectorConfig(min=1, max=10, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
