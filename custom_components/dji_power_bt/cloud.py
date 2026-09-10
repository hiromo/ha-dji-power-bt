"""Experimental DJI account client used only to obtain a local BLE pair key.

Normal integration operation is local BLE. Account passwords and member tokens are
kept only in the config-flow object and are never written to the config entry.
The endpoints are private DJI Home APIs and may change without notice.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import re
import time
import uuid

import aiohttp

ACCOUNT_BASE = "https://account.dji.com/apis/apprest/v1"
HOME_API_HOSTS = (
    "https://home-api.djigate.com",
    "https://home-api-vg.djigate.com",
    "https://home-api-hz.djigate.com",
)
DEVICES_PATH = "/app/api/v1/users/devices/list"
USER_AGENT = "DJIHome/1.5.16 (Android)"

# The DJI Home account-center request signature key is an implementation detail
# recovered by third-party interoperability research. It may be rotated by DJI.
# Base85 obscures the literal in source; it does not provide encryption or secrecy.
_DEFAULT_SIGNING_KEY_B85 = b"G&3|ZF=Q}dEn_fZW-T-{Ha9IfH8e6UGch$eV`DZjFfe0c"
_SIGNING_KEY = base64.b85decode(_DEFAULT_SIGNING_KEY_B85).decode("ascii")

CODE_OK = 0
CODE_EMAIL_CODE_REQUIRED = 553
CODE_EMAIL_FREQUENCY_LIMITED = 554
CODE_TWO_STEP_REQUIRED = 556
CODE_SMS_REACHED_LIMIT = 508
CODE_IMAGE_CAPTCHA_ERROR = 523
CODE_IMAGE_CAPTCHA_REQUIRED = 524
CODE_CAPTCHA_VERIFY_ERROR = 601
IMAGE_CAPTCHA_CODES = frozenset(
    {CODE_IMAGE_CAPTCHA_ERROR, CODE_IMAGE_CAPTCHA_REQUIRED, CODE_CAPTCHA_VERIFY_ERROR}
)
TWO_FACTOR_CODES = frozenset({CODE_EMAIL_CODE_REQUIRED, CODE_TWO_STEP_REQUIRED})
RATE_LIMIT_CODES = frozenset({CODE_EMAIL_FREQUENCY_LIMITED, CODE_SMS_REACHED_LIMIT})


class DjiCloudError(Exception):
    """Base DJI cloud error."""


class DjiAuthError(DjiCloudError):
    """Account or CAPTCHA request was rejected."""

    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(f"DJI cloud error {code}: {message}")
        self.code = code
        self.message = message


class DjiTwoFactorRequired(DjiCloudError):
    """The account requires an email/two-step code."""


class DjiRateLimited(DjiCloudError):
    """DJI rate-limited the verification request."""


@dataclass(frozen=True, slots=True)
class DjiCloudDevice:
    """One cloud device exposing a local BLE pair key."""

    name: str
    serial_number: str
    pair_uuid: str
    pair_key: str


def _signed_headers(client_name: str, device_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    invoke_id = f"DeviceId-Mc{timestamp}{uuid.uuid4().hex[:6]}"
    material = (
        "AppId-Mc"
        "cr-app"
        "ClientName-Mc"
        f"{client_name}"
        "DeviceId-Mc"
        f"{device_id}"
        "InvokeId-Mc"
        f"{invoke_id}"
        "Timestamp-Mc"
        f"{timestamp}"
    )
    signature = base64.b64encode(
        hmac.new(_SIGNING_KEY.encode(), material.encode(), hashlib.sha1).digest()
    ).decode()
    return {
        "ClientName-Mc": client_name,
        "DeviceId-Mc": device_id,
        "AppId-Mc": "cr-app",
        "Timestamp-Mc": timestamp,
        "InvokeId-Mc": invoke_id,
        "Sign-Mc": signature,
        "X-Risk-Version": "1.0",
        "X-DJI-SDK-Version": "1.0.0",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }


class DjiCloudClient:
    """Small async client for a one-time pair-key lookup."""

    def __init__(self, session: aiohttp.ClientSession, *, timeout: float = 20.0) -> None:
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._client_name = "android-1.5.16"
        self._device_id = f"dji-home-{uuid.uuid4().hex[:16]}"

    async def _post_account(self, action: str, data: dict[str, str]) -> dict:
        async with self._session.post(
            f"{ACCOUNT_BASE}/{action}",
            headers=_signed_headers(self._client_name, self._device_id),
            data=data,
            timeout=self._timeout,
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        if not isinstance(payload, dict):
            raise DjiCloudError("DJI account response was not an object")
        return payload

    async def get_image_captcha(self) -> tuple[str, bytes]:
        """Return the CAPTCHA request id and image bytes."""
        request_id = uuid.uuid4().hex
        headers = _signed_headers(self._client_name, self._device_id)
        headers.pop("Content-Type", None)
        async with self._session.get(
            f"{ACCOUNT_BASE}/vcode?srandom={request_id}",
            headers=headers,
            timeout=self._timeout,
        ) as response:
            response.raise_for_status()
            return request_id, await response.read()

    async def exchange_image_captcha(self, request_id: str, answer: str) -> str:
        payload = await self._post_account(
            "validate_captcha",
            {
                "captchaType": "imageCaptcha",
                "captchaModule": "AppLogin",
                "verificationCode": answer,
                "srandom": request_id,
            },
        )
        code = payload.get("code")
        if code != CODE_OK:
            raise DjiAuthError(code, str(payload.get("message") or "CAPTCHA rejected"))
        ticket = (payload.get("data") or {}).get("captchaTicket")
        if not ticket:
            raise DjiAuthError(code, "CAPTCHA response did not contain a ticket")
        return str(ticket)

    async def login(
        self,
        email: str,
        password: str,
        captcha_ticket: str,
        *,
        email_code: str | None = None,
    ) -> str:
        body = {
            "userName": email,
            "password": password,
            "captchaTicket": captcha_ticket,
        }
        if email_code:
            # DJI's private two-step flow is not publicly documented. Both field
            # names have been observed in app-side request models.
            body["emailCode"] = email_code
            body["verificationCode"] = email_code
        payload = await self._post_account("user_login", body)
        code = payload.get("code")
        if code in TWO_FACTOR_CODES:
            raise DjiTwoFactorRequired("DJI two-step verification is required")
        if code in RATE_LIMIT_CODES:
            raise DjiRateLimited(str(payload.get("message") or "rate limited"))
        if code != CODE_OK:
            raise DjiAuthError(code, str(payload.get("message") or "login failed"))
        token = (payload.get("data") or {}).get("token")
        if not isinstance(token, str) or not token:
            raise DjiAuthError(code, "login response did not contain a member token")
        return token

    async def list_devices(self, member_token: str) -> list[DjiCloudDevice]:
        """Return devices that have a 32-character local pair key."""
        last_error: Exception | None = None
        for host in HOME_API_HOSTS:
            try:
                async with self._session.get(
                    f"{host}{DEVICES_PATH}",
                    headers={
                        "x-member-token": member_token,
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                    },
                    timeout=self._timeout,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as error:
                last_error = error
                continue
            devices = _extract_devices(payload)
            if devices:
                return devices
        if last_error is not None:
            raise DjiCloudError(f"DJI Home device list failed: {last_error}")
        return []


def _extract_devices(payload: object) -> list[DjiCloudDevice]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return []
    result: list[DjiCloudDevice] = []
    for collection_name in ("dy_devices", "cr_devices"):
        collection = data.get(collection_name) or []
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            base = item.get("base_info") or {}
            pair = item.get("pair_info") or {}
            if not isinstance(base, dict) or not isinstance(pair, dict):
                continue
            pair_key = pair.get("pair_key")
            if not isinstance(pair_key, str) or re.fullmatch(r"[0-9a-fA-F]{32}", pair_key.strip()) is None:
                continue
            result.append(
                DjiCloudDevice(
                    name=str(base.get("name") or "DJI Power"),
                    serial_number=str(base.get("sn") or ""),
                    pair_uuid=str(pair.get("pair_uuid") or ""),
                    pair_key=pair_key.strip().lower(),
                )
            )
    return result
