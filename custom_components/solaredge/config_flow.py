"""Config flow for SolarEdge."""

from collections.abc import Mapping
import logging
import time
from typing import Any, cast, override

from aiohttp import ClientError, ClientResponseError
import probatio
from solaredge_web import SolarEdgeWeb

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigFlowResult
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import (
    OAuth2TokenRequestConnectionError,
    OAuth2TokenRequestError,
)
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    SolarEdgeApiError,
    SolarEdgeAuthError,
    SolarEdgeNotFoundError,
    SolarEdgeV2,
)
from .application_credentials import (
    SolarEdgeOAuth2Implementation,
    async_register_pending_oauth_flow,
    parse_oauth_redirect,
)
from .const import (
    CONF_REDIRECT_URL,
    CONF_SECTION_WEB_AUTH,
    CONF_SITE_ID,
    DEFAULT_NAME,
    DOMAIN,
    LOGGER,
    OAUTH2_REDIRECT_URI,
)


class SolarEdgeConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle a SolarEdge config flow."""

    VERSION = 2
    DOMAIN = DOMAIN

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._pending_data: dict[str, Any] = {}
        self._authorize_url: str | None = None
        self._update_entry: ConfigEntry | None = None

    @property
    @override
    def logger(self) -> logging.Logger:
        """Return the logger."""
        return LOGGER

    def _expected_site_id(self) -> str:
        """Return the site ID this flow is authorizing."""
        if self.source == SOURCE_REAUTH:
            return self._get_reauth_entry().data[CONF_SITE_ID]
        if self._update_entry is not None:
            return self._update_entry.data[CONF_SITE_ID]
        return self._pending_data[CONF_SITE_ID]

    def _entry_to_update(self) -> ConfigEntry | None:
        """Return an existing entry that this OAuth flow should update."""
        if self.source == SOURCE_REAUTH:
            return self._get_reauth_entry()
        if self._update_entry is not None:
            return self._update_entry
        return None

    async def _async_check_web_login(
        self, site_id: str, username: str, password: str
    ) -> str | None:
        """Validate SolarEdge web credentials."""
        api = SolarEdgeWeb(
            username=username,
            password=password,
            site_id=site_id,
            session=async_get_clientsession(self.hass),
        )
        try:
            await api.async_get_equipment()
        except ClientResponseError as err:
            return "invalid_auth" if err.status in (401, 403) else "cannot_connect"
        except TimeoutError, ClientError:
            return "cannot_connect"
        return None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the site ID before starting OAuth."""
        # After Application Credentials are created, HA often resumes at this
        # step even for reauth. Never re-ask for the site ID in that case.
        if self.source == SOURCE_REAUTH:
            return await self.async_step_reauth_confirm()

        errors: dict[str, str] = {}
        if user_input is not None:
            site_id = user_input[CONF_SITE_ID]
            existing = await self.async_set_unique_id(site_id)
            # Existing API-key / broken entries must be updated in place so
            # entity unique IDs and Energy Dashboard history are preserved.
            self._update_entry = existing

            web_auth = user_input.get(CONF_SECTION_WEB_AUTH, {})
            if username := web_auth.get(CONF_USERNAME):
                if error := await self._async_check_web_login(
                    site_id, username, web_auth[CONF_PASSWORD]
                ):
                    errors["base"] = error
                else:
                    self._pending_data = {
                        CONF_SITE_ID: site_id,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: web_auth[CONF_PASSWORD],
                    }
            else:
                self._pending_data = {CONF_SITE_ID: site_id}
                if existing is not None:
                    # Keep optional web credentials already stored on the entry.
                    if CONF_USERNAME in existing.data:
                        self._pending_data[CONF_USERNAME] = existing.data[CONF_USERNAME]
                    if CONF_PASSWORD in existing.data:
                        self._pending_data[CONF_PASSWORD] = existing.data[CONF_PASSWORD]

            if not errors:
                async_register_pending_oauth_flow(self.hass, site_id, self.flow_id)
                return await self.async_step_pick_implementation()

        schema = probatio.Schema(
            {
                probatio.Required(
                    CONF_SITE_ID,
                    default=(user_input or {}).get(CONF_SITE_ID, ""),
                ): str,
                probatio.Optional(CONF_SECTION_WEB_AUTH): section(
                    probatio.Schema(
                        {
                            probatio.Inclusive(
                                CONF_USERNAME, "web_account", default=""
                            ): str,
                            probatio.Inclusive(
                                probatio.Secret(CONF_PASSWORD),
                                "web_account",
                                default="",
                            ): str,
                        }
                    ),
                    options={"collapsed": True},
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication."""
        await self.async_set_unique_id(entry_data[CONF_SITE_ID])
        self._update_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauthentication."""
        entry = self._get_reauth_entry()
        site_id = entry.data[CONF_SITE_ID]
        self._update_entry = entry
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={"site_id": site_id},
            )
        async_register_pending_oauth_flow(self.hass, site_id, self.flow_id)
        return await self.async_step_pick_implementation()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure optional module-level web credentials."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            web_auth = user_input.get(CONF_SECTION_WEB_AUTH, {})
            new_data = dict(entry.data)
            new_data.pop(CONF_USERNAME, None)
            new_data.pop(CONF_PASSWORD, None)
            if username := web_auth.get(CONF_USERNAME):
                if error := await self._async_check_web_login(
                    entry.data[CONF_SITE_ID], username, web_auth[CONF_PASSWORD]
                ):
                    errors["base"] = error
                else:
                    new_data[CONF_USERNAME] = username
                    new_data[CONF_PASSWORD] = web_auth[CONF_PASSWORD]
            if not errors:
                return self.async_update_reload_and_abort(entry, data=new_data)

        suggested = {
            CONF_SECTION_WEB_AUTH: {
                CONF_USERNAME: entry.data.get(CONF_USERNAME, ""),
                CONF_PASSWORD: entry.data.get(CONF_PASSWORD, ""),
            }
        }
        schema = probatio.Schema(
            {
                probatio.Optional(CONF_SECTION_WEB_AUTH): section(
                    probatio.Schema(
                        {
                            probatio.Inclusive(
                                CONF_USERNAME, "web_account", default=""
                            ): str,
                            probatio.Inclusive(
                                probatio.Secret(CONF_PASSWORD),
                                "web_account",
                                default="",
                            ): str,
                        }
                    ),
                    options={"collapsed": False},
                )
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or suggested
            ),
            errors=errors,
            description_placeholders={"site_id": entry.data[CONF_SITE_ID]},
        )

    @override
    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Use paste-code OAuth (SolarEdge omits state; no HA public URL)."""
        return await self.async_step_paste()

    async def async_step_paste(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Authorize at SolarEdge, then paste the static-page redirect URL."""
        errors: dict[str, str] = {}
        authorize_url = await self._async_authorize_url()

        if user_input is not None:
            parsed = parse_oauth_redirect(user_input[CONF_REDIRECT_URL])
            if "error" in parsed:
                errors["base"] = "oauth_rejected"
            elif "code" not in parsed:
                errors["base"] = "invalid_redirect_url"
            else:
                expected_site = self._expected_site_id()
                returned_site = parsed.get(CONF_SITE_ID) or parsed.get("siteId")
                if returned_site and str(returned_site) != str(expected_site):
                    errors["base"] = "wrong_account"
                else:
                    implementation = cast(
                        SolarEdgeOAuth2Implementation, self.flow_impl
                    )
                    try:
                        token = await implementation.async_exchange_code(
                            self.flow_id,
                            parsed["code"],
                            OAUTH2_REDIRECT_URI,
                        )
                        token["expires_in"] = int(token["expires_in"])
                        token["expires_at"] = time.time() + float(token["expires_in"])
                    except (
                        OAuth2TokenRequestConnectionError,
                        OAuth2TokenRequestError,
                        KeyError,
                        TypeError,
                        ValueError,
                    ) as err:
                        LOGGER.warning("SolarEdge token exchange failed: %s", err)
                        errors["base"] = "oauth_failed"
                    else:
                        return await self.async_oauth_create_entry(
                            {
                                "auth_implementation": self.flow_impl.domain,
                                CONF_TOKEN: token,
                            }
                        )

        schema = probatio.Schema(
            {
                probatio.Required(CONF_REDIRECT_URL): str,
            }
        )
        return self.async_show_form(
            step_id="paste",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "authorize_url": authorize_url,
                "redirect_url": OAUTH2_REDIRECT_URI,
            },
        )

    async def _async_authorize_url(self) -> str:
        """Return a stable authorize URL for this flow."""
        if self._authorize_url is None:
            self._authorize_url = await self.flow_impl.async_generate_authorize_url(
                self.flow_id
            )
        return self._authorize_url

    @override
    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Validate OAuth access and create or update the entry."""
        entry = self._entry_to_update()
        site_id = self._expected_site_id()

        token = data[CONF_TOKEN]

        async def async_get_access_token() -> str:
            return token[CONF_ACCESS_TOKEN]

        api = SolarEdgeV2(async_get_clientsession(self.hass), async_get_access_token)
        try:
            response = await api.get_details(site_id)
            details = response["details"]
        except SolarEdgeAuthError:
            return self.async_abort(reason="oauth_unauthorized")
        except SolarEdgeNotFoundError:
            return self.async_abort(
                reason="wrong_account" if entry is not None else "cannot_connect"
            )
        except SolarEdgeApiError, KeyError:
            return self.async_abort(reason="cannot_connect")

        if str(details.get("status", "")).lower() != "active":
            return self.async_abort(reason="site_not_active")

        await self.async_set_unique_id(site_id)
        if entry is not None:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            new_data = {**entry.data, **self._pending_data, **data, CONF_SITE_ID: site_id}
            new_data.pop(CONF_API_KEY, None)
            return self.async_update_reload_and_abort(
                entry,
                data=new_data,
                title=details.get("name") or entry.title or DEFAULT_NAME,
            )

        return self.async_create_entry(
            title=details.get("name") or DEFAULT_NAME,
            data={**self._pending_data, **data},
        )
