"""Server-side login, resumable cloud requests and installation selection."""

import time

import probatio

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from homeassistant.helpers.storage import Store

from .client import AuthError, CloudClient, CloudError, login_sync
from .const import CONF_INSTALLATION_ID, CONF_REFRESH_TOKEN, DOMAIN


class CloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._client = None
        self._installations = []
        self._reauth = False
        self._username = ""

    @property
    def _pending_store(self):
        owner = self.context.get("user_id") or "owner"
        return Store(self.hass, 1, f"{DOMAIN}.pending_auth.{owner}", private=True, atomic_writes=True)

    def _new_client(self, username, session):
        return CloudClient(async_get_clientsession(self.hass), self.hass.async_add_executor_job,
                           username, session[CONF_REFRESH_TOKEN], auth_session=session)

    def _login_form(self, errors):
        username = probatio.Required(CONF_USERNAME, default=self._username) if self._username else probatio.Required(CONF_USERNAME)
        return self.async_show_form(step_id="user", data_schema=probatio.Schema({
            username: str,
            probatio.Required(probatio.Secret(CONF_PASSWORD)): str,
        }), errors=errors)

    async def async_step_user(self, user_input=None):
        if user_input is None and not self._reauth:
            pending = await self._pending_store.async_load()
            if pending and pending.get("expires_at", 0) > time.time() + 30:
                self._username = pending[CONF_USERNAME]
                self._client = self._new_client(self._username, pending["session"])
                return await self.async_step_connection({})
            if pending:
                await self._pending_store.async_remove()
        if user_input is None:
            return self._login_form({})
        self._username = user_input[CONF_USERNAME].strip()
        try:
            session = await self.hass.async_add_executor_job(login_sync, self._username, user_input[CONF_PASSWORD])
        except AuthError as error:
            key = "additional_auth" if error.stage == "challenge" else "invalid_auth" if error.stage == "login" else "session_auth"
            return self._login_form({"base": key})
        except CloudError:
            return self._login_form({"base": "cannot_connect"})
        # Cache a successful sign-in privately for at most 15 minutes, so a
        # failed cloud request/restart does not require the password again.
        await self._pending_store.async_save({
            CONF_USERNAME: self._username, "session": session,
            "expires_at": min(time.time() + 900, session["expires_at"] - 30),
        })
        self._client = self._new_client(self._username, session)
        return await self.async_step_connection({})

    async def async_step_connection(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._installations = await self._client.installations()
                if not self._installations:
                    errors["base"] = "no_installations"
                elif self._reauth:
                    entry = self._get_reauth_entry()
                    if not any(row.get("id") == entry.data[CONF_INSTALLATION_ID] for row in self._installations):
                        return self._login_form({"base": "wrong_account"})
                    self.hass.data.setdefault(DOMAIN, {})[entry.unique_id] = self._client
                    await self._pending_store.async_remove()
                    return self.async_update_reload_and_abort(entry, data_updates={
                        CONF_USERNAME: self._username, CONF_REFRESH_TOKEN: self._client.refresh_token,
                        "device_key": self._client.device_key})
                else:
                    return await self.async_step_installation()
            except AuthError as error:
                if error.stage == "identity":
                    errors["base"] = "cloud_authorization"
                else:
                    await self._pending_store.async_remove()
                    return self._login_form({"base": "session_auth"})
            except CloudError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="connection", data_schema=probatio.Schema({}), errors=errors)

    async def async_step_installation(self, user_input=None):
        if user_input is None and len(self._installations) == 1:
            user_input = {CONF_INSTALLATION_ID: self._installations[0]["id"]}
        if user_input is not None:
            installation_id = user_input[CONF_INSTALLATION_ID]
            if not any(row.get("id") == installation_id for row in self._installations):
                return self.async_abort(reason="not_found")
            await self.async_set_unique_id(installation_id)
            self._abort_if_unique_id_configured()
            row = next(row for row in self._installations if row.get("id") == installation_id)
            self.hass.data.setdefault(DOMAIN, {})[installation_id] = self._client
            await self._pending_store.async_remove()
            return self.async_create_entry(title=row.get("customName") or "Rekuperator ecoNET Cloud", data={
                CONF_USERNAME: self._username,
                CONF_REFRESH_TOKEN: self._client.refresh_token,
                CONF_INSTALLATION_ID: installation_id,
                "device_key": self._client.device_key,
            })
        options = [{"value": row["id"], "label": row.get("customName") or row.get("name") or "ecoNET Cloud"}
                   for row in self._installations]
        return self.async_show_form(step_id="installation", data_schema=probatio.Schema({
            probatio.Required(CONF_INSTALLATION_ID): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options))}))

    async def async_step_reauth(self, entry_data):
        self._reauth = True
        self._username = entry_data.get(CONF_USERNAME, "")
        return await self.async_step_user()
