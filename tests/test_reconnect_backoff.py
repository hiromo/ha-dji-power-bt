"""Reconnect retry policy and bounded disconnect timing diagnostics."""
import asyncio
from types import SimpleNamespace

import pytest
import test_manager_v070 as base


@pytest.mark.parametrize("outcome", ["ok", "timeout", "error", "cancelled", "skip", "forced", "connected"])
def test_disconnect_measurement_excludes_notify_stop(monkeypatch, outcome):
    async def scenario():
        item = base.make_manager()
        clock = [100.0]
        real_timeout = asyncio.timeout
        monkeypatch.setattr(base.manager_connection_mod, "asyncio", SimpleNamespace(
            get_running_loop=lambda: SimpleNamespace(time=lambda: clock[0]),
            timeout=lambda seconds: real_timeout(0.001 if outcome == "timeout" and seconds == 3 else seconds),
            CancelledError=asyncio.CancelledError,
        ))
        class Client:
            is_connected = outcome not in ("skip", "forced")
            async def stop_notify(self, _uuid):
                clock[0] += 7.0
                # Capture connection state after notification shutdown, not before.
                if outcome != "connected":
                    self.is_connected = False
            async def disconnect(self):
                clock[0] += 0.125
                if outcome == "timeout":
                    await asyncio.Event().wait()
                if outcome == "error":
                    raise RuntimeError("synthetic failure")
                if outcome == "cancelled":
                    raise asyncio.CancelledError
        client = Client()
        kwargs = dict(stop_notify=True, force=outcome != "skip", context="test", expected=False)
        if outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await item._disconnect_client(client, **kwargs)
        else:
            await item._disconnect_client(client, **kwargs)
        events = item.connection_event_history
        result = [e for e in events if e["event"] == "disconnect_complete"]
        assert len(result) == 1
        event = result[0]
        assert event["disconnect_started_connected"] == (outcome == "connected")
        assert event["disconnect_duration_s"] == (None if outcome == "skip" else 0.125)
        assert event["disconnect_result"] == {
            "error": "error:RuntimeError", "skip": "already_disconnected", "forced": "ok", "connected": "ok"
        }.get(outcome, outcome)
        requested = next(e for e in events if e["event"] == "disconnect_requested")
        assert requested["client_is_connected"] == (outcome not in ("skip", "forced"))
    asyncio.run(scenario())


def test_retry_loop_caps_at_sixty_and_resets_after_success(monkeypatch):
    async def scenario():
        item = base.make_manager()
        delays = []
        attempts = [0]
        async def connect():
            attempts[0] += 1
            if attempts[0] == 8:
                item.state.connected = item.state.authenticated = True
                return
            raise base.manager_mod.DjiPowerConnectionError("synthetic failure")
        async def disconnect(*, reason):
            item.state.connected = item.state.authenticated = False
        async def wait(delay):
            delays.append(delay)
            if attempts[0] == 9:
                item._stopping = True
        async def sleep(_delay):
            # Simulate a subsequent link loss after the successful ready transition.
            assert item.state.connection_phase == "ready"
            assert item.state.consecutive_connect_failures == 0
            item.state.connected = item.state.authenticated = False
        item._connect_auth_and_init = connect
        item.async_disconnect = disconnect
        item._wait_retry_delay = wait
        item._connection_health_issue = lambda: None
        item._reachability_diagnostics = lambda: None
        monkeypatch.setattr(base.manager_connection_mod, "asyncio", SimpleNamespace(
            get_running_loop=asyncio.get_running_loop, sleep=sleep, CancelledError=asyncio.CancelledError))
        await item._run_loop()
        assert attempts[0] == 9
        assert delays == [10, 20, 30, 60, 60, 60, 60, 10]
        events = [e for e in item.connection_event_history if e["event"] == "retry_scheduled"]
        assert [e["retry_delay_s"] for e in events] == delays
    asyncio.run(scenario())
