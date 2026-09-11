"""BLE connection lifecycle mixin for DJI Power.

The public manager remains in manager.py. This module isolates reconnect, scanner
resolution and client ownership so those concerns can be reviewed independently.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any
import weakref

from bleak import BleakClient
from bleak.exc import BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache, close_stale_connections_by_address, establish_connection,
)
from homeassistant.components import bluetooth

from .capabilities import capabilities_for_model_code
from .const import CHAR_NOTIFY_C305, DJI_COMPANY_ID
from .manager_constants import (
    ESTABLISH_CONNECTION_MAX_ATTEMPTS, EXPECTED_DISCONNECT_RECORD_TTL_SECONDS,
    FRESH_ADVERTISEMENT_TIMEOUT_SECONDS, NOTIFY_WATCHDOG_TIMEOUT,
    RECONNECT_BACKOFF_SECONDS,
    STALE_CONNECTION_CLEANUP_FIRST_FAILURE_COUNT, STALE_CONNECTION_CLEANUP_INTERVAL,
    START_NOTIFY_TIMEOUT, UNEXPECTED_DISCONNECT_SETTLE_SECONDS,
)
from .manager_types import DjiPowerConnectionError
from .manager_utils import (
    classify_connection_exception, client_is_connected, client_object_id, safe_device_source,
    utcnow_iso,
)
from .protocol import DumlReassembler, normalize_address, parse_manufacturer_data

_LOGGER = logging.getLogger(__name__)

class ManagerConnectionMixin:
    @property
    def connection_event_history(self) -> list[dict[str, Any]]:
        """Return this device's bounded connection event history."""
        return list(self._local_connection_event_history)

    @property
    def client_lifecycle_diagnostics(self) -> dict[str, Any]:
        """Return current client ownership and reconnect-gate diagnostics."""
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            now = None
        disconnect_age = (
            max(0.0, now - self._unexpected_disconnect_monotonic)
            if now is not None and self._unexpected_disconnect_monotonic is not None
            else None
        )
        settle_remaining = (
            max(0.0, self._reconnect_not_before_monotonic - now)
            if (
                now is not None
                and self._reconnect_not_before_monotonic is not None
                and self._fresh_advertisement_required
            )
            else None
        )
        # Diagnostics may discard dead weak-reference records, but must not
        # expire a live expected callback earlier than the existing lifecycle
        # logic would. Age-based pruning remains tied to disconnect operations.
        self._prune_expected_disconnect_clients()
        return {
            "active_client_present": self._client is not None,
            "active_client_id": client_object_id(self._client),
            "active_client_is_connected": client_is_connected(self._client),
            "retired_client_present": self._retired_client is not None,
            "retired_client_id": client_object_id(self._retired_client),
            "retired_client_is_connected": client_is_connected(self._retired_client),
            "expected_disconnect_client_count": len(
                self._expected_disconnect_client_ids
            ),
            "fresh_advertisement_required": self._fresh_advertisement_required,
            "fresh_advertisement_received_at": self._fresh_advertisement_received_at,
            "last_unexpected_disconnect_age_s": disconnect_age,
            "reconnect_settle_remaining_s": settle_remaining,
            "active_connection_attempt_id": self._active_connection_attempt_id,
        }

    def _next_connection_attempt_id(self) -> int:
        runtime = self._domain_runtime
        allocator = getattr(runtime, "next_connection_attempt_id", None)
        if callable(allocator):
            return int(allocator())
        value = self._local_next_connection_attempt_id
        self._local_next_connection_attempt_id += 1
        return value

    def _record_connection_event(
        self,
        event: str,
        *,
        attempt_id: int | None = None,
        client: BleakClient | None = None,
        expected_disconnect: bool | None = None,
        exception: BaseException | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record one local and domain-wide connection lifecycle event."""
        try:
            monotonic_time = asyncio.get_running_loop().time()
        except RuntimeError:
            monotonic_time = None
        record: dict[str, Any] = {
            "recorded_at": utcnow_iso(),
            "monotonic_time": monotonic_time,
            "entry_id": getattr(self.entry, "entry_id", None),
            "model": self.model,
            "address": self.address,
            "event": event,
            "phase": self.state.connection_phase,
            "attempt_id": (
                self._active_connection_attempt_id
                if attempt_id is None
                else attempt_id
            ),
            "connection_generation": self._connection_generation,
            "client_id": client_object_id(client),
            "client_is_connected": client_is_connected(client),
            "expected_disconnect": expected_disconnect,
            "scanner_source": self.state.bluetooth_source
            or self.state.advertisement_source,
            "device_resolution": self.state.last_device_resolution,
            "fresh_advertisement_required": self._fresh_advertisement_required,
        }
        if exception is not None:
            record["exception_class"] = type(exception).__name__
            record["exception_message"] = str(exception)
        if details:
            record.update(details)

        runtime = self._domain_runtime
        recorder = getattr(runtime, "record_connection_event", None)
        if callable(recorder):
            event_id = int(recorder(record))
        else:
            event_id = self._local_next_connection_event_id
            self._local_next_connection_event_id += 1
        local_record = dict(record)
        local_record["event_id"] = event_id
        self._local_connection_event_history.append(local_record)

    @contextlib.asynccontextmanager
    async def _connection_operation(
        self,
        context: str,
        *,
        attempt_id: int | None = None,
    ):
        """Serialize controller operations and expose lock contention in diagnostics."""
        loop = asyncio.get_running_loop()
        wait_started = loop.time()
        runtime = self._domain_runtime
        if runtime is not None and hasattr(runtime, "connection_lock_waiters"):
            runtime.connection_lock_waiters += 1
        self._record_connection_event(
            "connection_lock_wait_start",
            attempt_id=attempt_id,
            details={"lock_context": context},
        )
        acquired = False
        try:
            await self._connection_operation_lock.acquire()
            acquired = True
        finally:
            if runtime is not None and hasattr(runtime, "connection_lock_waiters"):
                runtime.connection_lock_waiters = max(
                    0, runtime.connection_lock_waiters - 1
                )
        wait_duration = max(0.0, loop.time() - wait_started)
        if runtime is not None and hasattr(runtime, "connection_lock_holder"):
            runtime.connection_lock_holder = (
                f"{getattr(self.entry, 'entry_id', 'unknown')}:{context}"
            )
        self._record_connection_event(
            "connection_lock_acquired",
            attempt_id=attempt_id,
            details={
                "lock_context": context,
                "lock_wait_s": wait_duration,
            },
        )
        try:
            yield
        finally:
            if runtime is not None and hasattr(runtime, "connection_lock_holder"):
                runtime.connection_lock_holder = None
            if acquired and self._connection_operation_lock.locked():
                self._connection_operation_lock.release()
            self._record_connection_event(
                "connection_lock_released",
                attempt_id=attempt_id,
                details={"lock_context": context},
            )
    async def _run_loop(self) -> None:
        backoff_index = 0
        while not self._stopping:
            if not self.state.ble_enabled:
                await asyncio.sleep(1)
                continue

            if not self.state.connected:
                try:
                    self.state.connection_phase = "connecting"
                    await self._connect_auth_and_init()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # connection loop must survive
                    self.state.consecutive_connect_failures += 1
                    self.state.last_error = f"{type(exc).__name__}: {exc}"
                    self.state.last_connection_error = self.state.last_error
                    self.state.last_connection_error_at = utcnow_iso()
                    delay = RECONNECT_BACKOFF_SECONDS[
                        min(backoff_index, len(RECONNECT_BACKOFF_SECONDS) - 1)
                    ]
                    backoff_index += 1
                    self.state.last_retry_delay_s = delay
                    self.state.connection_phase = "backoff"
                    self._record_connection_event(
                        "retry_scheduled",
                        exception=exc,
                        details={
                            "retry_delay_s": delay,
                            "consecutive_connect_failures": (
                                self.state.consecutive_connect_failures
                            ),
                            "failure_category": (
                                self.state.last_connection_failure_category
                            ),
                            "failure_phase": (
                                self.state.last_connection_failure_phase
                            ),
                        },
                    )
                    _LOGGER.warning(
                        "DJI Power BLE connection failed for %s; retry in %.0fs "
                        "(consecutive failures=%d): %s",
                        self.address,
                        delay,
                        self.state.consecutive_connect_failures,
                        self.state.last_error,
                    )
                    reachability = self._reachability_diagnostics()
                    if reachability:
                        _LOGGER.warning(
                            "DJI Power Bluetooth reachability for %s: %s",
                            self.address,
                            reachability,
                        )
                    self._notify_listeners()
                    await self.async_disconnect(reason="connect_error")
                    self.state.connection_phase = "backoff"
                    self._notify_listeners()
                    await self._wait_retry_delay(delay)
                    continue
                else:
                    backoff_index = 0
                    self.state.consecutive_connect_failures = 0
                    self.state.last_retry_delay_s = None
                    self.state.connection_phase = "ready"
                    self._last_stale_cleanup_failure_count = 0

            health_issue = self._connection_health_issue()
            if health_issue is not None:
                self.state.last_error = health_issue
                self.state.last_connection_error = health_issue
                self.state.last_connection_error_at = utcnow_iso()
                self._record_connection_event(
                    "connection_health_failed",
                    details={"health_issue": health_issue},
                )
                _LOGGER.warning(
                    "DJI Power BLE health check failed for %s: %s",
                    self.address,
                    health_issue,
                )
                self._notify_listeners()
                await self.async_disconnect(reason=health_issue)
                self.state.connection_phase = "backoff"
                self._notify_listeners()
                await self._wait_retry_delay(RECONNECT_BACKOFF_SECONDS[0])
                continue

            await asyncio.sleep(1)

    async def _wait_retry_delay(self, delay: float) -> None:
        """Wait for retry delay, but allow a manual reconnect to wake it early."""
        self._retry_wakeup.clear()
        try:
            await asyncio.wait_for(self._retry_wakeup.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    async def _connect_auth_and_init(self) -> None:
        """Connect, subscribe, authenticate and fetch initial config."""
        async with self._connect_lock:
            if self.state.connected:
                return

            attempt_id = self._next_connection_attempt_id()
            self._active_connection_attempt_id = attempt_id
            self._active_connection_attempt_started_monotonic = (
                asyncio.get_running_loop().time()
            )
            self._active_connection_failure_phase = None
            self._record_connection_event(
                "connect_attempt_start",
                attempt_id=attempt_id,
            )
            try:
                device = await self._resolve_device_for_connection(attempt_id)
                async with self._connection_operation(
                    "connect_setup", attempt_id=attempt_id
                ):
                    self._reset_protocol_state()
                    await self._maybe_cleanup_stale_connections()
                    client: BleakClient | None = None
                    try:
                        self.state.connection_phase = "connecting"
                        client = await self._establish_client(device)
                        self._client = client
                        self._record_connected_client(client, device)
                        try:
                            self.state.connection_phase = "subscribing"
                            self._record_connection_event(
                                "notify_start_requested",
                                attempt_id=attempt_id,
                                client=client,
                            )
                            async with asyncio.timeout(START_NOTIFY_TIMEOUT):
                                await client.start_notify(
                                    CHAR_NOTIFY_C305, self._notification_callback(client)
                                )
                            self._record_connection_event(
                                "notify_started",
                                attempt_id=attempt_id,
                                client=client,
                            )
                        except (BleakError, TimeoutError) as exc:
                            self._record_connection_event(
                                "notify_start_failed",
                                attempt_id=attempt_id,
                                client=client,
                                exception=exc,
                            )
                            _LOGGER.warning(
                                "start_notify failed for %s; clearing GATT cache and retrying once",
                                self.address,
                            )
                            clear_cache = getattr(client, "clear_cache", None)
                            if clear_cache is not None:
                                with contextlib.suppress(AttributeError, BleakError):
                                    await clear_cache()
                            await self._disconnect_client(
                                client,
                                stop_notify=False,
                                force=True,
                                context="notify_retry",
                                expected=True,
                            )
                            if self._client is client:
                                self._client = None
                            client = await self._establish_client(device)
                            self._client = client
                            self._record_connected_client(client, device)
                            self.state.connection_phase = "subscribing"
                            self._record_connection_event(
                                "notify_start_requested",
                                attempt_id=attempt_id,
                                client=client,
                                details={"retry": True},
                            )
                            async with asyncio.timeout(START_NOTIFY_TIMEOUT):
                                await client.start_notify(
                                    CHAR_NOTIFY_C305, self._notification_callback(client)
                                )
                            self._record_connection_event(
                                "notify_started",
                                attempt_id=attempt_id,
                                client=client,
                                details={"retry": True},
                            )

                        await asyncio.sleep(0.2)
                        self.state.connection_phase = "authenticating"
                        self._record_connection_event(
                            "authentication_start",
                            attempt_id=attempt_id,
                            client=client,
                        )
                        await self._authenticate()
                        self._record_connection_event(
                            "authenticated",
                            attempt_id=attempt_id,
                            client=client,
                        )
                        self.state.identity_status = (
                            "dji_manufacturer_and_protocol_verified"
                            if DJI_COMPANY_ID in self.state.manufacturer_ids
                            else "dji_protocol_authenticated_address_only"
                        )
                        self.state.connection_phase = "initial_config"
                        cfg = await self._read_current_config()
                        self._apply_config(cfg, source="0x60_initial", notify=False)
                        if self._last_notify_monotonic is None:
                            self._last_notify_monotonic = (
                                asyncio.get_running_loop().time()
                            )
                        self.state.connection_phase = "ready"
                        self._mark_connection_ready()
                        self._record_connection_event(
                            "initial_config_complete",
                            attempt_id=attempt_id,
                            client=client,
                        )
                        self._notify_listeners()
                    except asyncio.CancelledError:
                        self._active_connection_failure_phase = (
                            self._active_connection_failure_phase or self.state.connection_phase
                        )
                        await self._abort_connection_setup(client)
                        raise
                    except Exception:
                        self._active_connection_failure_phase = (
                            self._active_connection_failure_phase or self.state.connection_phase
                        )
                        await self._abort_connection_setup(client)
                        raise
            except asyncio.CancelledError as exc:
                started = self._active_connection_attempt_started_monotonic
                duration = (
                    max(0.0, asyncio.get_running_loop().time() - started)
                    if started is not None
                    else None
                )
                self._record_connection_event(
                    "connect_attempt_cancelled",
                    attempt_id=attempt_id,
                    expected_disconnect=True,
                    exception=exc,
                    details={
                        "attempt_duration_s": duration,
                        "cancelled_phase": (
                            self._active_connection_failure_phase
                            or self.state.connection_phase
                        ),
                    },
                )
                raise
            except Exception as exc:
                started = self._active_connection_attempt_started_monotonic
                duration = (
                    max(0.0, asyncio.get_running_loop().time() - started)
                    if started is not None
                    else None
                )
                failure_category = classify_connection_exception(exc)
                failure_phase = (
                    self._active_connection_failure_phase
                    or self.state.connection_phase
                )
                self.state.last_connection_failure_category = failure_category
                self.state.last_connection_failure_phase = failure_phase
                self._record_connection_event(
                    "connect_attempt_failed",
                    attempt_id=attempt_id,
                    exception=exc,
                    details={
                        "attempt_duration_s": duration,
                        "failure_category": failure_category,
                        "failure_phase": failure_phase,
                    },
                )
                raise
            else:
                started = self._active_connection_attempt_started_monotonic
                duration = (
                    max(0.0, asyncio.get_running_loop().time() - started)
                    if started is not None
                    else None
                )
                self._record_connection_event(
                    "connect_attempt_ready",
                    attempt_id=attempt_id,
                    client=self._client,
                    details={"attempt_duration_s": duration},
                )
            finally:
                self._active_connection_attempt_id = None
                self._active_connection_attempt_started_monotonic = None
                self._active_connection_failure_phase = None

    async def _resolve_device_for_connection(self, attempt_id: int) -> BLEDevice:
        """Resolve a device, requiring a post-disconnect advertisement when needed."""
        if self._retired_client is not None:
            retired = self._retired_client
            async with self._connection_operation(
                "retired_client_cleanup", attempt_id=attempt_id
            ):
                await self._disconnect_client(
                    retired,
                    stop_notify=False,
                    force=True,
                    context="retired_client_cleanup",
                    # This client already delivered the unexpected-disconnect
                    # callback that moved it into the retired slot. A second
                    # callback is optional, so do not register it as pending.
                    expected=False,
                )
            if self._retired_client is retired:
                self._retired_client = None
            if self._fresh_advertisement_required:
                cleanup_settle_deadline = (
                    asyncio.get_running_loop().time()
                    + UNEXPECTED_DISCONNECT_SETTLE_SECONDS
                )
                self._reconnect_not_before_monotonic = max(
                    self._reconnect_not_before_monotonic or 0.0,
                    cleanup_settle_deadline,
                )

        if self._fresh_advertisement_required:
            return await self._wait_for_fresh_advertisement(attempt_id)

        self.state.connection_phase = "resolving"
        return await self._find_device()

    async def _wait_for_fresh_advertisement(self, attempt_id: int) -> BLEDevice:
        """Wait for a new connectable advertisement after an unexpected disconnect."""
        loop = asyncio.get_running_loop()
        if self._reconnect_not_before_monotonic is not None:
            remaining = self._reconnect_not_before_monotonic - loop.time()
            if remaining > 0:
                self.state.connection_phase = "disconnect_settle"
                self._record_connection_event(
                    "unexpected_disconnect_settle_start",
                    attempt_id=attempt_id,
                    details={"settle_delay_s": remaining},
                )
                await asyncio.sleep(remaining)

        self.state.connection_phase = "waiting_fresh_advertisement"
        self._record_connection_event(
            "fresh_advertisement_wait_start",
            attempt_id=attempt_id,
            details={
                "timeout_s": FRESH_ADVERTISEMENT_TIMEOUT_SECONDS,
            },
        )

        clear_history = getattr(
            bluetooth, "async_clear_advertisement_history", None
        )
        if callable(clear_history):
            clear_history(self.hass, self.address)

        process_advertisements = getattr(
            bluetooth, "async_process_advertisements", None
        )
        scanning_mode = getattr(bluetooth, "BluetoothScanningMode", None)
        if callable(process_advertisements) and scanning_mode is not None:
            def _matches(service_info: Any) -> bool:
                try:
                    return normalize_address(service_info.address) == self.address
                except Exception:
                    return False

            try:
                service_info = await process_advertisements(
                    self.hass,
                    _matches,
                    {"address": self.address, "connectable": True},
                    scanning_mode.PASSIVE,
                    FRESH_ADVERTISEMENT_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                self._record_connection_event(
                    "fresh_advertisement_wait_timeout",
                    attempt_id=attempt_id,
                    exception=exc,
                )
                raise DjiPowerConnectionError(
                    "No fresh connectable advertisement was received after the "
                    "unexpected BLE disconnect"
                ) from exc
            device = service_info.device
            self._validate_and_record_ble_device(
                device, resolution="fresh_after_disconnect"
            )
        else:
            # Compatibility fallback for older Home Assistant releases. The target
            # release supports async_process_advertisements; this branch avoids a
            # hard import failure while still forbidding the manager's cached device.
            self._last_ble_device = None
            device = await self._find_device(allow_cached=False)

        self._last_ble_device = device
        self._cached_device_retry_used = False
        self._fresh_advertisement_required = False
        self._reconnect_not_before_monotonic = None
        self._fresh_advertisement_received_at = utcnow_iso()
        self.state.connection_phase = "resolving"
        self._record_connection_event(
            "fresh_advertisement_received",
            attempt_id=attempt_id,
            details={
                "advertisement_source": self.state.advertisement_source,
            },
        )
        _LOGGER.debug(
            "DJI Power fresh advertisement received for %s via %s",
            self.address,
            self.state.advertisement_source,
        )
        return device

    async def _establish_client(self, device: BLEDevice) -> BleakClient:
        self._record_connection_event(
            "gatt_connect_start",
            client=None,
            details={
                "max_attempts": ESTABLISH_CONNECTION_MAX_ATTEMPTS,
                "timeout_s": 30.0,
                "device_source": safe_device_source(device),
            },
        )
        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            name=self.connector_name,
            disconnected_callback=self._disconnected_callback,
            max_attempts=ESTABLISH_CONNECTION_MAX_ATTEMPTS,
            timeout=30.0,
        )
        self._record_connection_event(
            "gatt_connected",
            client=client,
            details={"device_source": safe_device_source(device)},
        )
        if not client.is_connected:
            raise DjiPowerConnectionError("BLE client disconnected during setup")
        client_address = normalize_address(client.address)
        if client_address != self.address:
            await self._disconnect_client(
                client,
                stop_notify=False,
                force=True,
                context="address_mismatch",
                expected=True,
            )
            raise DjiPowerConnectionError(
                f"Connected BLE address mismatch: expected {self.address}, got {client_address}"
            )
        return client

    async def _maybe_cleanup_stale_connections(self) -> None:
        failures = self.state.consecutive_connect_failures
        if failures < STALE_CONNECTION_CLEANUP_FIRST_FAILURE_COUNT:
            return
        if failures == self._last_stale_cleanup_failure_count:
            return
        if (
            failures - STALE_CONNECTION_CLEANUP_FIRST_FAILURE_COUNT
        ) % STALE_CONNECTION_CLEANUP_INTERVAL != 0:
            return
        self._last_stale_cleanup_failure_count = failures
        try:
            async with asyncio.timeout(10):
                await close_stale_connections_by_address(self.address)
        except Exception as exc:  # best-effort BlueZ recovery
            _LOGGER.debug(
                "Failed to clear stale DJI Power connections for %s: %s",
                self.address,
                exc,
            )
            return
        self.state.stale_connection_cleanup_count += 1
        self.state.last_stale_connection_cleanup_at = utcnow_iso()

    def _mark_connection_ready(self) -> None:
        """Record a fully initialized/authenticated connection becoming ready."""
        self.state.last_ready_at = utcnow_iso()
        if self._ever_ready:
            self.state.successful_reconnect_count += 1
        else:
            self._ever_ready = True

    def _record_connected_client(self, client: BleakClient, device: BLEDevice) -> None:
        self._connection_generation += 1
        self.state.connected = True
        self.state.authenticated = False
        self.state.last_error = None
        self.state.last_gatt_connect_at = utcnow_iso()
        self.state.gatt_connect_count += 1
        # Keep the previous disconnect reason/time after recovery so a diagnostic
        # downloaded during the new connection still explains why it reconnected.
        self.state.bluetooth_source = safe_device_source(device)
        self._transport_unhealthy_reason = None
        if self._ever_connected:
            self.state.gatt_reconnect_count += 1
        else:
            self._ever_connected = True
        self._record_connection_event(
            "client_adopted",
            client=client,
            details={"device_source": self.state.bluetooth_source},
        )
        self._notify_listeners()

    async def _abort_connection_setup(self, client: BleakClient | None) -> None:
        self._fail_pending_requests(DjiPowerConnectionError("connection setup aborted"))
        if client is not None:
            # If the backend already delivered an unexpected-disconnect callback,
            # _handle_disconnected_callback() has moved this same client into the
            # retired slot.  Request backend cleanup, but do not register another
            # expected callback: a second callback is optional. Weak-reference
            # tracking no longer owns the client, but registering an already
            # delivered callback would still leave a stale expected record and
            # misrepresent this lifecycle in diagnostics.
            expect_callback = self._retired_client is not client
            await self._disconnect_client(
                client,
                stop_notify=True,
                force=True,
                context="connection_setup_abort",
                expected=expect_callback,
            )
        if self._client is client:
            self._client = None
        if self._retired_client is client:
            self._retired_client = None
        self.state.connected = False
        self.state.authenticated = False
        self.state.connection_phase = "idle"
        self._cancel_write_verifications()
        self._cancel_ack_tasks()
        self._cancel_telemetry_publish()
        self._reset_protocol_state()
        self._notify_listeners()

    async def async_disconnect(self, *, reason: str) -> None:
        async with self._connect_lock:
            preserve_reconnect_gate = (
                reason == "connect_error" and self._fresh_advertisement_required
            )
            client = self._client
            retired_client = self._retired_client
            self.state.connected = False
            self.state.authenticated = False
            self.state.connection_phase = "disconnecting"
            if not preserve_reconnect_gate:
                self.state.last_disconnect_reason = reason
                self.state.last_disconnect_at = utcnow_iso()
            self._last_notify_monotonic = None
            self._fail_pending_requests(
                DjiPowerConnectionError(f"disconnected: {reason}")
            )
            self._cancel_write_verifications()
            self._cancel_ack_tasks()
            self._cancel_telemetry_publish()
            self._reset_protocol_state()
            self._record_connection_event(
                "disconnect_sequence_start",
                client=client,
                expected_disconnect=True,
                details={
                    "disconnect_reason": reason,
                    "retired_client_present": retired_client is not None,
                },
            )
            clients: list[tuple[BleakClient, str, bool, bool]] = []
            if client is not None:
                clients.append((client, "active_client", True, True))
            if retired_client is not None and retired_client is not client:
                # A retired client has already delivered its disconnect callback.
                # Request backend cleanup, but never wait for a second callback.
                clients.append((retired_client, "retired_client", False, False))

            if clients:
                async with self._connection_operation("disconnect"):
                    for target, role, stop_notify, expect_callback in clients:
                        await self._disconnect_client(
                            target,
                            stop_notify=stop_notify,
                            force=True,
                            context=f"{reason}:{role}",
                            expected=expect_callback,
                        )

            if self._client is client:
                self._client = None
            if self._retired_client is retired_client:
                self._retired_client = None
            if not preserve_reconnect_gate:
                self._fresh_advertisement_required = False
                self._unexpected_disconnect_monotonic = None
                self._reconnect_not_before_monotonic = None
            _LOGGER.debug("DJI Power disconnected: %s", reason)
            self.state.connection_phase = "idle"
            self._record_connection_event(
                "disconnect_sequence_complete",
                expected_disconnect=True,
                details={"disconnect_reason": reason},
            )
            self._notify_listeners()

    def _prune_expected_disconnect_clients(self, *, now: float | None = None) -> None:
        """Drop expired or dead expected-disconnect records without owning clients."""
        self._expected_disconnect_client_ids = {
            key: value
            for key, value in self._expected_disconnect_client_ids.items()
            if value[0]() is not None
            and (
                now is None
                or now - value[1] < EXPECTED_DISCONNECT_RECORD_TTL_SECONDS
            )
        }

    async def _disconnect_client(
        self,
        client: BleakClient,
        *,
        stop_notify: bool,
        force: bool = False,
        context: str,
        expected: bool,
    ) -> str:
        """Request backend cleanup and retain the result in connection diagnostics."""
        client_id = id(client)
        now = asyncio.get_running_loop().time()
        self._prune_expected_disconnect_clients(now=now)
        if expected:
            # Track expected callbacks without making this bookkeeping table an
            # owner of the BleakClient. If the backend never emits the callback,
            # the client can still be garbage-collected once all real lifecycle
            # owners release it. Dead records are pruned from diagnostics and on
            # the next disconnect operation.
            self._expected_disconnect_client_ids[client_id] = (
                weakref.ref(client),
                now,
            )
        self._record_connection_event(
            "disconnect_requested",
            client=client,
            expected_disconnect=expected,
            details={
                "disconnect_context": context,
                "force": force,
                "stop_notify": stop_notify,
            },
        )

        stop_notify_result = "not_requested"
        if stop_notify and client_is_connected(client):
            try:
                async with asyncio.timeout(2):
                    await client.stop_notify(CHAR_NOTIFY_C305)
            except TimeoutError:
                stop_notify_result = "timeout"
            except Exception as exc:
                stop_notify_result = f"error:{type(exc).__name__}"
                self._record_connection_event(
                    "stop_notify_failed",
                    client=client,
                    expected_disconnect=expected,
                    exception=exc,
                    details={"disconnect_context": context},
                )
            else:
                stop_notify_result = "ok"

        disconnect_result = "already_disconnected"
        if force or client_is_connected(client):
            try:
                async with asyncio.timeout(3):
                    await client.disconnect()
            except TimeoutError as exc:
                disconnect_result = "timeout"
                self._record_connection_event(
                    "disconnect_failed",
                    client=client,
                    expected_disconnect=expected,
                    exception=exc,
                    details={
                        "disconnect_context": context,
                        "disconnect_result": disconnect_result,
                    },
                )
            except Exception as exc:
                disconnect_result = f"error:{type(exc).__name__}"
                self._record_connection_event(
                    "disconnect_failed",
                    client=client,
                    expected_disconnect=expected,
                    exception=exc,
                    details={
                        "disconnect_context": context,
                        "disconnect_result": disconnect_result,
                    },
                )
            else:
                disconnect_result = "ok"

        self._record_connection_event(
            "disconnect_complete",
            client=client,
            expected_disconnect=expected,
            details={
                "disconnect_context": context,
                "stop_notify_result": stop_notify_result,
                "disconnect_result": disconnect_result,
            },
        )
        return disconnect_result

    def _reset_protocol_state(self) -> None:
        self._reassembler = DumlReassembler()
        self._transport_unhealthy_reason = None
        # Never reuse a pre-disconnect configuration snapshot on a new BLE link,
        # even when reconnection occurs within the normal cache-age window.
        self._last_config_report_monotonic = None
        self._unconfirmed_config_writes.clear()

    def _disconnected_callback(self, client: BleakClient) -> None:
        self.hass.loop.call_soon_threadsafe(self._handle_disconnected_callback, client)

    def _handle_disconnected_callback(self, client: BleakClient) -> None:
        client_id = id(client)
        expected_record = self._expected_disconnect_client_ids.get(client_id)
        expected_client = expected_record[0]() if expected_record is not None else None
        expected = expected_client is client
        if expected or (expected_record is not None and expected_client is None):
            self._expected_disconnect_client_ids.pop(client_id, None)
        is_active = self._client is client
        self._record_connection_event(
            "disconnect_callback",
            client=client,
            expected_disconnect=expected,
            details={
                "callback_for_active_client": is_active,
                "callback_for_retired_client": self._retired_client is client,
            },
        )

        if expected:
            if is_active:
                self._client = None
            if self._retired_client is client:
                self._retired_client = None
            return

        if not is_active:
            self._record_connection_event(
                "stale_disconnect_callback_ignored",
                client=client,
                expected_disconnect=False,
            )
            _LOGGER.debug(
                "Ignoring stale DJI Power disconnect callback for %s", self.address
            )
            return

        if (
            self._active_connection_attempt_id is not None
            and self.state.connection_phase != "ready"
        ):
            self._active_connection_failure_phase = (
                self._active_connection_failure_phase or self.state.connection_phase
            )
        self._client = None
        self._retired_client = client
        self.state.connected = False
        self.state.authenticated = False
        self.state.connection_phase = "idle"
        self.state.last_disconnect_reason = "unexpected_disconnect"
        self.state.last_disconnect_at = utcnow_iso()
        self._last_notify_monotonic = None
        self._unexpected_disconnect_monotonic = asyncio.get_running_loop().time()
        self._reconnect_not_before_monotonic = (
            self._unexpected_disconnect_monotonic
            + UNEXPECTED_DISCONNECT_SETTLE_SECONDS
        )
        self._fresh_advertisement_required = True
        self._fresh_advertisement_received_at = None
        # A BLEDevice resolved before this disconnect may point at a client/backend
        # lifecycle that is still being torn down. Never use it for the next link.
        self._last_ble_device = None
        self._cached_device_retry_used = True
        self._fail_pending_requests(DjiPowerConnectionError("unexpected BLE disconnect"))
        self._cancel_write_verifications()
        self._cancel_ack_tasks()
        self._cancel_telemetry_publish()
        self._reset_protocol_state()
        _LOGGER.warning(
            "DJI Power unexpected BLE disconnect for %s; waiting for a fresh "
            "advertisement before reconnecting",
            self.address,
        )
        self._record_connection_event(
            "unexpected_disconnect_reconnect_gate_armed",
            client=client,
            expected_disconnect=False,
            details={
                "settle_seconds": UNEXPECTED_DISCONNECT_SETTLE_SECONDS,
                "fresh_advertisement_timeout_s": (
                    FRESH_ADVERTISEMENT_TIMEOUT_SECONDS
                ),
            },
        )
        self._notify_listeners()

    async def _find_device(self, *, allow_cached: bool = True) -> BLEDevice:
        """Resolve this exact address through Home Assistant's Bluetooth manager."""
        scanner_count = getattr(bluetooth, "async_scanner_count", None)
        if scanner_count is not None and scanner_count(self.hass, connectable=True) == 0:
            raise DjiPowerConnectionError(
                "No connectable Home Assistant Bluetooth scanner is available"
            )

        wait_seconds = min(max(self.scan_timeout, 1.0), 15.0)
        deadline = asyncio.get_running_loop().time() + wait_seconds
        process_advertisements = getattr(bluetooth, "async_process_advertisements", None)
        scanning_mode = getattr(bluetooth, "BluetoothScanningMode", None)
        while True:
            device = bluetooth.async_ble_device_from_address(
                self.hass,
                self.address,
                connectable=True,
            )
            if device is not None:
                self._validate_and_record_ble_device(device, resolution="ha_current")
                self._last_ble_device = device
                self._cached_device_retry_used = False
                return device

            if callable(process_advertisements) and scanning_mode is not None:
                def matches(service_info: Any) -> bool:
                    try:
                        return normalize_address(service_info.address) == self.address
                    except (AttributeError, ValueError):
                        return False

                try:
                    service_info = await process_advertisements(
                        self.hass, matches,
                        {"address": self.address, "connectable": True},
                        scanning_mode.PASSIVE, wait_seconds,
                    )
                except TimeoutError:
                    break
                device = service_info.device
                self._validate_and_record_ble_device(device, resolution="ha_current")
                self._last_ble_device = device
                self._cached_device_retry_used = False
                return device

            # Compatibility only: supported HA versions wait on advertisements.
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(1.0)

        if (
            allow_cached
            and not self._fresh_advertisement_required
            and self._last_ble_device is not None
            and not self._cached_device_retry_used
        ):
            self._cached_device_retry_used = True
            self._validate_and_record_ble_device(
                self._last_ble_device,
                resolution="ha_cached",
            )
            _LOGGER.warning(
                "DJI Power %s is temporarily absent from current HA Bluetooth history; "
                "retrying with the last HA-provided BLEDevice",
                self.address,
            )
            self._record_connection_event(
                "cached_ble_device_used",
                details={"allow_cached": allow_cached},
            )
            return self._last_ble_device

        if self._cached_device_retry_used:
            self._last_ble_device = None

        self.state.last_device_resolution = "unavailable"
        self.state.identity_status = "address_unavailable"
        reason = self._reachability_diagnostics()
        raise DjiPowerConnectionError(
            f"DJI Power {self.address} is not reachable via Home Assistant Bluetooth"
            + (f": {reason}" if reason else "")
        )

    def _validate_and_record_ble_device(
        self,
        device: BLEDevice,
        *,
        resolution: str,
    ) -> None:
        """Hard-bind a manager to one BLE address and record advertisement identity.

        The device name is never used to select a connection. If Home Assistant ever
        returns a device for another address, the connection is rejected before Bleak
        is allowed to use it. When manufacturer data is present, a non-DJI company ID
        is also rejected. Missing manufacturer data is tolerated because some cached
        advertisements contain only partial fields; 0x6A authentication remains the
        final protocol-level identity check.
        """
        resolved_address = normalize_address(device.address)
        self.state.last_device_resolution = resolution
        self.state.resolved_ble_address = resolved_address
        self.state.resolved_ble_name = device.name

        if resolved_address != self.address:
            self.state.identity_status = "ble_address_mismatch"
            raise DjiPowerConnectionError(
                f"HA Bluetooth resolved {resolved_address}, expected {self.address}"
            )

        service_info = bluetooth.async_last_service_info(
            self.hass,
            self.address,
            connectable=True,
        )
        if service_info is None:
            self.state.advertised_name = None
            self.state.advertisement_source = None
            self.state.manufacturer_ids = ()
            self.state.advertised_model_code = None
            self.state.advertised_model = None
            self.state.advertised_bound = None
            self.state.advertised_mac_candidate = None
            self.state.identity_status = "address_verified_no_advertisement_data"
            _LOGGER.debug(
                "DJI Power resolver: configured=%s resolved=%s BLEDevice.name=%r "
                "advertisement unavailable",
                self.address,
                resolved_address,
                device.name,
            )
            return

        advertised_address = normalize_address(service_info.address)
        self.state.advertised_name = service_info.name
        self.state.advertisement_source = service_info.source
        self.state.manufacturer_ids = tuple(sorted(service_info.manufacturer_data))

        if advertised_address != self.address:
            self.state.identity_status = "advertisement_address_mismatch"
            raise DjiPowerConnectionError(
                f"HA advertisement address mismatch: expected {self.address}, "
                f"got {advertised_address}"
            )

        manufacturer_ids = self.state.manufacturer_ids
        if manufacturer_ids and DJI_COMPANY_ID not in manufacturer_ids:
            self.state.identity_status = "manufacturer_mismatch"
            ids = ", ".join(f"0x{value:04X}" for value in manufacturer_ids)
            raise DjiPowerConnectionError(
                f"BLE address {self.address} advertises non-DJI manufacturer IDs: {ids}"
            )

        manufacturer_payload = service_info.manufacturer_data.get(DJI_COMPANY_ID)
        if manufacturer_payload:
            try:
                advertisement = parse_manufacturer_data(manufacturer_payload)
            except ValueError:
                _LOGGER.debug("Malformed DJI manufacturer data for %s", self.address)
            else:
                self.state.advertised_model_code = advertisement.model_code
                self.state.advertised_model = advertisement.model
                self.state.advertised_bound = advertisement.bound
                self.state.advertised_mac_candidate = advertisement.mac_candidate
                # Advertisement is the authoritative model signal at runtime.
                self.model_code = advertisement.model_code
                self.model = advertisement.model
                self.capabilities = capabilities_for_model_code(self.model_code)

        self.state.identity_status = (
            "dji_manufacturer_verified"
            if DJI_COMPANY_ID in manufacturer_ids
            else "address_verified_no_manufacturer_data"
        )
        _LOGGER.debug(
            "DJI Power resolver: configured=%s resolved=%s BLEDevice.name=%r "
            "advertised_name=%r manufacturer_ids=%s source=%s resolution=%s",
            self.address,
            resolved_address,
            device.name,
            service_info.name,
            [f"0x{value:04X}" for value in manufacturer_ids],
            service_info.source,
            resolution,
        )

    def _reachability_diagnostics(self) -> str | None:
        diagnostics = getattr(
            bluetooth,
            "async_address_reachability_diagnostics",
            None,
        )
        intent_class = getattr(bluetooth, "BluetoothReachabilityIntent", None)
        if diagnostics is None or intent_class is None:
            return None
        try:
            return diagnostics(
                self.hass,
                self.address,
                intent_class.CONNECTION,
            )
        except Exception as exc:  # noqa: diagnostics must never break reconnection
            _LOGGER.debug(
                "Failed to get Bluetooth reachability diagnostics: %s",
                exc,
            )
            return None

    def _connection_health_issue(self) -> str | None:
        if self._transport_unhealthy_reason is not None:
            return self._transport_unhealthy_reason
        client = self._client
        if client is None or not client.is_connected:
            return "transport_not_connected"

        if self.state.authenticated and self._last_notify_monotonic is not None:
            age = asyncio.get_running_loop().time() - self._last_notify_monotonic
            if age > NOTIFY_WATCHDOG_TIMEOUT:
                return f"notify_watchdog_timeout_{age:.1f}s"
        return None
