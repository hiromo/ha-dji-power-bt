# BLE protocol transport

## GATT characteristics

**Confirmed in current implementation**

- Write characteristic: `0000c304-0000-1000-8000-00805f9b34fb`
- Notify characteristic: `0000c305-0000-1000-8000-00805f9b34fb`

The manager writes complete DUM-like frames to C304 and receives an arbitrary byte stream through C305 notifications.

## Notification boundaries are not frame boundaries

A single DJI frame may be split across multiple ATT notifications, and a notification may contain multiple DJI frames. Never parse one BLE notification as one application frame.

`DumlReassembler` buffers bytes and extracts frames using:

1. sync byte `0x55`;
2. encoded frame length;
3. DJI header CRC8;
4. DJI frame CRC16.

Malformed data is resynchronized conservatively. Diagnostic counters include invalid length, header CRC failure, frame CRC failure, discarded bytes, buffered bytes, and partial-frame timeout.

## Request/response routing

Application requests use command set `0x5A` and an allocated 16-bit sequence number.

Pending requests are keyed by:

```text
(connection_generation, sequence)
```

A response satisfies a request only when all of the following match:

- current connection generation;
- sequence;
- command set;
- command ID;
- response command type `0x80`.

This prevents a delayed response from an old BLE link from completing a request on a new link after reconnect.

## GATT write serialization

Per-device GATT writes are serialized by `_write_lock`. The timeout covers both waiting for the lock and the backend `write_gatt_char()` call. Current timeout: 10 seconds.

A timeout marks the transport unhealthy, increments diagnostics, fails the operation, and leaves reconnect/error handling to the manager lifecycle.

## Persistent connection model

The integration intentionally keeps one persistent GATT connection per enabled
DJI Power Bluetooth config entry. Do not convert normal runtime polling/writes
into connect-per-operation behavior.

Connection setup/teardown is serialized across DJI Power entries through the shared domain connection-operation lock because Bluetooth adapters/proxies have finite connection resources and backend connect/disconnect transitions can overlap badly.

See `docs/implementation/bluetooth-lifecycle.md` for lifecycle details.

## Discovery identity

Home Assistant Bluetooth discovery uses DJI company/manufacturer ID `0x08AA`.

Observed manufacturer-data shape used by the integration:

```text
byte 0      model code
byte 1      flags; bit 0x10 is treated as bound
bytes 3..8  MAC-address candidate when present
```

Home Assistant normally strips the two-byte little-endian company ID from `manufacturer_data[0x08AA]`; the parser also accepts captured data that still includes it.

The configured normalized BLE address is the authoritative runtime identity. Name/model/manufacturer fields are diagnostics and discovery hints.

A station can temporarily emit a connectable name-only advertisement without
manufacturer data. The setup list deliberately does not accept that packet
because it cannot safely select a model profile. Field observations show that a
later advertisement can include `0x08AA`; users should ensure that DJI Home is
not holding the station's Bluetooth connection, wait, and retry discovery rather
than treating the first name-only packet as a supported identity source. DJI
Home Wi-Fi and cloud access do not conflict with this BLE discovery path.

## Home Assistant Bluetooth ownership

Use Home Assistant's Bluetooth stack and the `bluetooth` / `bluetooth_adapters` integration dependencies. Do not pin a second `bleak-retry-connector` requirement in this custom integration.

See ADR `0006-use-home-assistant-bluetooth-dependencies.md`.
