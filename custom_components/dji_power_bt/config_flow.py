"""Config flow for DJI Power."""
from __future__ import annotations

import base64
import contextlib
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .cloud import (
    IMAGE_CAPTCHA_CODES,
    DjiAuthError,
    DjiCloudClient,
    DjiCloudDevice,
    DjiCloudError,
    DjiRateLimited,
    DjiTwoFactorRequired,
)
from .const import (
    CONF_ADDRESS,
    CONF_CAPTCHA_CODE,
    CONF_DEVICE,
    CONF_DEVICE_NAME,
    CONF_EMAIL,
    CONF_LOCAL_AUTH_KEY,
    CONF_MEMBER_TOKEN,
    CONF_MODEL,
    CONF_MODEL_CODE,
    CONF_PASSWORD,
    CONF_SERIAL_NUMBER,
    CONF_TELEMETRY_UPDATE_INTERVAL,
    DEFAULT_TELEMETRY_UPDATE_INTERVAL,
    DJI_COMPANY_ID,
    DOMAIN,
    KNOWN_MODEL_CODES,
    MAX_TELEMETRY_UPDATE_INTERVAL,
    MIN_TELEMETRY_UPDATE_INTERVAL,
)
from .protocol import (
    normalize_address,
    parse_manufacturer_data,
    validate_local_auth_key,
)

CONF_CHANGE_AUTH_METHOD = "change_auth_method"


class DjiPowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up a DJI Power discovered by Home Assistant Bluetooth."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._advertised_name: str | None = None
        self._model_code: int | None = None
        self._model_name: str = "DJI Power"
        self._device_name: str | None = None
        self._cloud_client: DjiCloudClient | None = None
        self._cloud_devices: list[DjiCloudDevice] | None = None
        self._member_token: str | None = None
        self._email: str | None = None
        self._password: str | None = None
        self._captcha_request_id: str | None = None
        self._captcha_ticket: str | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    # ------------------------------------------------------------------ discovery

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> config_entries.ConfigFlowResult:
        """Handle an automatic Bluetooth discovery flow."""
        if not self._is_supported_service_info(discovery_info):
            return self.async_abort(reason="not_supported")
        self._select_service_info(discovery_info)
        await self.async_set_unique_id(self._address)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": self._model_name}
        return await self.async_step_auth_method()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """List currently advertising DJI Power devices."""
        return await self.async_step_select_device(user_input)

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        candidates = self._discovered_candidates()
        if not candidates:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            address = normalize_address(user_input[CONF_DEVICE])
            info = candidates.get(address)
            if info is None:
                return self.async_abort(reason="device_disappeared")
            self._select_service_info(info)
            await self.async_set_unique_id(self._address)
            self._abort_if_unique_id_configured()
            return await self.async_step_auth_method()

        labels = {
            address: self._candidate_label(info)
            for address, info in candidates.items()
        }
        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE, default=next(iter(labels))): vol.In(labels)}
            ),
        )

    async def async_step_auth_method(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose how to obtain the per-device local BLE pair key."""
        if self._address is None:
            return await self.async_step_select_device()
        return self.async_show_menu(
            step_id="auth_method",
            menu_options=["account", "token", "manual"],
        )

    # ------------------------------------------------------------------ manual key

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._change_auth_method_requested(user_input):
                return await self.async_step_auth_method()
            try:
                pair_key = validate_local_auth_key(
                    str(user_input.get(CONF_LOCAL_AUTH_KEY, ""))
                )
            except ValueError:
                errors[CONF_LOCAL_AUTH_KEY] = "invalid_key"
            else:
                self._device_name = (
                    user_input.get(CONF_DEVICE_NAME) or self._default_title
                )
                return await self._async_create_device_entry(pair_key=pair_key)

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHANGE_AUTH_METHOD, default=False
                    ): BooleanSelector(),
                    vol.Optional(CONF_LOCAL_AUTH_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_DEVICE_NAME, default=self._default_title): str,
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------ member token

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._change_auth_method_requested(user_input):
                return await self.async_step_auth_method()
            self._device_name = user_input.get(CONF_DEVICE_NAME) or self._default_title
            token = str(user_input.get(CONF_MEMBER_TOKEN, "")).strip()
            if not token:
                errors[CONF_MEMBER_TOKEN] = "required"
            else:
                self._cloud_client = DjiCloudClient(async_get_clientsession(self.hass))
                try:
                    self._cloud_devices = await self._cloud_client.list_devices(token)
                except DjiCloudError:
                    errors["base"] = "cloud_lookup_failed"
                else:
                    if not self._cloud_devices:
                        errors["base"] = "no_cloud_devices"
                    else:
                        return await self.async_step_cloud_device()

        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHANGE_AUTH_METHOD, default=False
                    ): BooleanSelector(),
                    vol.Optional(CONF_MEMBER_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_DEVICE_NAME, default=self._default_title): str,
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------ account login

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._change_auth_method_requested(user_input):
                return await self.async_step_auth_method()
            email = str(user_input.get(CONF_EMAIL, "")).strip()
            password = str(user_input.get(CONF_PASSWORD, ""))
            if not email:
                errors[CONF_EMAIL] = "required"
            if not password:
                errors[CONF_PASSWORD] = "required"
            if not errors:
                self._email = email
                self._password = password
                self._device_name = (
                    user_input.get(CONF_DEVICE_NAME) or self._default_title
                )
                self._cloud_client = DjiCloudClient(async_get_clientsession(self.hass))
                return await self.async_step_captcha()

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHANGE_AUTH_METHOD, default=False
                    ): BooleanSelector(),
                    vol.Optional(CONF_EMAIL): str,
                    vol.Optional(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_DEVICE_NAME, default=self._default_title): str,
                }
            ),
            errors=errors,
        )

    async def async_step_captcha(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._cloud_client is None or self._email is None or self._password is None:
            return await self.async_step_account()

        if user_input is not None:
            if self._change_auth_method_requested(user_input):
                return await self.async_step_auth_method()
            captcha_code = str(user_input.get(CONF_CAPTCHA_CODE, "")).strip()
            if not captcha_code:
                errors[CONF_CAPTCHA_CODE] = "required"
            else:
                try:
                    if self._captcha_request_id is None:
                        raise DjiCloudError("CAPTCHA request expired")
                    self._captcha_ticket = (
                        await self._cloud_client.exchange_image_captcha(
                            self._captcha_request_id,
                            captcha_code,
                        )
                    )
                    self._member_token = await self._cloud_client.login(
                        self._email,
                        self._password,
                        self._captcha_ticket,
                    )
                except DjiTwoFactorRequired:
                    return await self.async_step_two_factor()
                except DjiRateLimited:
                    errors["base"] = "rate_limited"
                except DjiAuthError as error:
                    errors["base"] = (
                        "invalid_captcha"
                        if error.code in IMAGE_CAPTCHA_CODES
                        else "login_failed"
                    )
                except DjiCloudError:
                    errors["base"] = "login_failed"
                else:
                    return await self._async_fetch_cloud_devices()

        try:
            self._captcha_request_id, image = (
                await self._cloud_client.get_image_captcha()
            )
        except (DjiCloudError, OSError):
            return self.async_abort(reason="cloud_lookup_failed")

        image_uri = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
        return self.async_show_form(
            step_id="captcha",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHANGE_AUTH_METHOD, default=False
                    ): BooleanSelector(),
                    vol.Optional(CONF_CAPTCHA_CODE): str,
                }
            ),
            errors=errors,
            description_placeholders={"image": image_uri},
        )

    async def async_step_two_factor(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._cloud_client is None or self._email is None or self._password is None:
            return await self.async_step_account()

        if user_input is not None:
            if self._change_auth_method_requested(user_input):
                return await self.async_step_auth_method()
            verification_code = str(user_input.get("code", "")).strip()
            if not verification_code:
                errors["code"] = "required"
            else:
                try:
                    self._member_token = await self._cloud_client.login(
                        self._email,
                        self._password,
                        self._captcha_ticket or "",
                        email_code=verification_code,
                    )
                except DjiTwoFactorRequired:
                    errors["base"] = "invalid_code"
                except DjiRateLimited:
                    errors["base"] = "rate_limited"
                except DjiCloudError:
                    errors["base"] = "login_failed"
                else:
                    return await self._async_fetch_cloud_devices()

        return self.async_show_form(
            step_id="two_factor",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHANGE_AUTH_METHOD, default=False
                    ): BooleanSelector(),
                    vol.Optional("code"): str,
                }
            ),
            errors=errors,
        )

    async def _async_fetch_cloud_devices(self) -> config_entries.ConfigFlowResult:
        assert self._cloud_client is not None and self._member_token is not None
        try:
            self._cloud_devices = await self._cloud_client.list_devices(
                self._member_token
            )
        except DjiCloudError:
            return self.async_abort(reason="cloud_lookup_failed")
        finally:
            # The member token is not needed after this one lookup.
            self._member_token = None
            self._password = None
            self._captcha_ticket = None
        if not self._cloud_devices:
            return self.async_abort(reason="no_cloud_devices")
        return await self.async_step_cloud_device()

    async def async_step_cloud_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        devices = self._cloud_devices or []
        if not devices:
            return self.async_abort(reason="no_cloud_devices")
        if len(devices) == 1:
            return await self._async_create_device_entry(
                pair_key=devices[0].pair_key,
                serial_number=devices[0].serial_number,
            )

        options = {
            str(index): (
                f"{device.name} ({device.serial_number})"
                if device.serial_number
                else f"{device.name} [{index + 1}]"
            )
            for index, device in enumerate(devices)
        }
        if user_input is not None:
            if self._change_auth_method_requested(user_input):
                return await self.async_step_auth_method()
            index = int(user_input[CONF_DEVICE])
            if 0 <= index < len(devices):
                device = devices[index]
                return await self._async_create_device_entry(
                    pair_key=device.pair_key,
                    serial_number=device.serial_number,
                )

        return self.async_show_form(
            step_id="cloud_device",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHANGE_AUTH_METHOD, default=False
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_DEVICE, default=next(iter(options))
                    ): vol.In(options),
                }
            ),
        )

    # ------------------------------------------------------------------ reauth/options

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and self._reauth_entry is not None:
            try:
                new_key = validate_local_auth_key(user_input[CONF_LOCAL_AUTH_KEY])
            except ValueError:
                errors[CONF_LOCAL_AUTH_KEY] = "invalid_key"
            else:
                data = dict(self._reauth_entry.data)
                data[CONF_LOCAL_AUTH_KEY] = new_key
                self.hass.config_entries.async_update_entry(self._reauth_entry, data=data)
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCAL_AUTH_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "DjiPowerOptionsFlowHandler":
        return DjiPowerOptionsFlowHandler()

    # ------------------------------------------------------------------ helpers

    @property
    def _default_title(self) -> str:
        return self._advertised_name or self._model_name or "DJI Power"

    def _is_supported_service_info(self, info: BluetoothServiceInfoBleak) -> bool:
        # Requiring DJI manufacturer data prevents a non-DJI device merely named
        # "Power..." (for example a smart plug) from appearing as a candidate.
        manufacturer_data = (info.manufacturer_data or {}).get(DJI_COMPANY_ID)
        if not manufacturer_data:
            return False
        try:
            advertisement = parse_manufacturer_data(manufacturer_data)
        except ValueError:
            return False
        return (
            advertisement.model_code in KNOWN_MODEL_CODES
            or (info.name or "").casefold().startswith("power")
        )

    def _discovered_candidates(self) -> dict[str, BluetoothServiceInfoBleak]:
        configured = {
            normalize_address(entry.data.get(CONF_ADDRESS, ""))
            for entry in self._async_current_entries()
        }
        candidates: dict[str, BluetoothServiceInfoBleak] = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            address = normalize_address(info.address)
            if address in configured or not self._is_supported_service_info(info):
                continue
            candidates[address] = info
        return dict(sorted(candidates.items()))

    def _candidate_label(self, info: BluetoothServiceInfoBleak) -> str:
        model_name = "DJI Power"
        model_code: int | None = None
        manufacturer_data = (info.manufacturer_data or {}).get(DJI_COMPANY_ID)
        if manufacturer_data:
            with contextlib.suppress(ValueError):
                advertisement = parse_manufacturer_data(manufacturer_data)
                model_name = advertisement.model
                model_code = advertisement.model_code
        advertised_name = info.name or "(no BLE name)"
        code_suffix = f", model 0x{model_code:02X}" if model_code is not None else ""
        return f"{model_name} — {advertised_name} ({normalize_address(info.address)}{code_suffix})"

    def _select_service_info(self, info: BluetoothServiceInfoBleak) -> None:
        self._address = normalize_address(info.address)
        self._advertised_name = info.name or "DJI Power"
        manufacturer_data = (info.manufacturer_data or {}).get(DJI_COMPANY_ID)
        if manufacturer_data:
            with contextlib.suppress(ValueError):
                advertisement = parse_manufacturer_data(manufacturer_data)
                self._model_code = advertisement.model_code
                self._model_name = advertisement.model

    def _change_auth_method_requested(self, user_input: dict[str, Any]) -> bool:
        """Clear setup-only authentication state when returning to the method menu."""
        if not user_input.get(CONF_CHANGE_AUTH_METHOD):
            return False

        # Home Assistant resumes discovery config flows at their last server-side
        # step, and closing the frontend dialog does not call integration code.
        # Every setup form therefore provides an explicit, reversible route back.
        self._cloud_client = None
        self._cloud_devices = None
        self._member_token = None
        self._email = None
        self._password = None
        self._captcha_request_id = None
        self._captcha_ticket = None
        return True

    async def _async_create_device_entry(
        self,
        *,
        pair_key: str,
        serial_number: str = "",
    ) -> config_entries.ConfigFlowResult:
        if self._address is None:
            return self.async_abort(reason="device_disappeared")
        try:
            normalized_key = validate_local_auth_key(pair_key)
        except ValueError:
            return self.async_abort(reason="invalid_pair_key_from_cloud")
        await self.async_set_unique_id(self._address, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        data: dict[str, Any] = {
            CONF_ADDRESS: self._address,
            CONF_DEVICE_NAME: self._device_name or self._default_title,
            CONF_LOCAL_AUTH_KEY: normalized_key,
            CONF_MODEL: self._model_name,
        }
        if self._model_code is not None:
            data[CONF_MODEL_CODE] = self._model_code
        if serial_number:
            data[CONF_SERIAL_NUMBER] = serial_number
        return self.async_create_entry(
            title=self._device_name or self._default_title,
            data=data,
        )


class DjiPowerOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Runtime options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TELEMETRY_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_TELEMETRY_UPDATE_INTERVAL,
                            self.config_entry.data.get(
                                CONF_TELEMETRY_UPDATE_INTERVAL,
                                DEFAULT_TELEMETRY_UPDATE_INTERVAL,
                            ),
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_TELEMETRY_UPDATE_INTERVAL,
                            max=MAX_TELEMETRY_UPDATE_INTERVAL,
                        ),
                    ),
                }
            ),
        )
