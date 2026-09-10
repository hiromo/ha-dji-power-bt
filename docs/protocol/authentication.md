# Authentication and pair keys

## Local pair key

The runtime authentication secret is a 32-character ASCII hexadecimal pair key. The integration normalizes it to lowercase after validation.

The pair key is stored in the Home Assistant config entry because it is required for future local BLE authentication. Protect the Home Assistant host and backups accordingly.

The integration does not provide a GUI, diagnostic, log, or payload-capture
surface for displaying the key. An administrator can recover a previously
stored key by inspecting `data.local_auth_key` in the matching
`dji_power_bt` entry inside `/config/.storage/core.config_entries`.
Inspection reveals the secret and must be performed privately and read-only;
never edit `.storage` manually or publish the result.

## Pair-key acquisition methods

The config flow supports three setup paths:

1. obtain the pair key from a DJI account through an experimental private DJI Home API flow;
2. obtain it from an already acquired DJI member token;
3. enter a known 32-character hexadecimal pair key manually.

The account/member-token paths are setup conveniences only. Normal integration runtime must remain local BLE.

Account email, account password, CAPTCHA answer/ticket, and member token must not be persisted into the config entry. The private DJI endpoints may change without notice.

The account client stores its bundled request-signing key as Base85-encoded
bytes and restores the original ASCII string when the module is loaded. This
only obscures the literal in source; it is not encryption or a secrecy guarantee
and does not change request signatures.

Because those private endpoints are not a durable recovery contract, a user may
store an already acquired pair key in an encrypted password manager or secret
vault. Never store it in repository Markdown, issues, screenshots, unencrypted
captures, or public automation YAML.

## Last-resort recovery from owned-device traffic

**Confirmed protocol property; security-sensitive**

The second `0x6A` authentication request contains the 32-character pair key as
ASCII hexadecimal bytes. A user who owns and is authorized to inspect the
station can therefore recover the key by capturing and analyzing the BLE
authentication exchange between DJI Home and that station if cloud acquisition
is no longer available.

This is a last-resort secret-recovery technique, not a diagnostic feature.
Authentication captures must remain private and should be deleted or encrypted
after recovery. Never capture traffic belonging to a device or user without
authorization.

## Command 0x6A authentication

**Confirmed current implementation**

Authentication uses command set `0x5A`, command `0x6A`, in two requests.

### Step 1: obtain session material

Send:

```text
cmd_id  = 0x6A
payload = 00
```

The response must contain at least five payload bytes and payload byte 0 must be zero. Bytes 1..4 are reused in the second request.

### Step 2: authenticate with the pair key

Build:

```text
01
+ session_response_payload[1:5]
+ 32 ASCII hex pair-key bytes
+ 00
```

Send that as another `0x6A` request. Authentication succeeds when the response payload is non-empty and response byte 0 is zero.

Only after this step does the manager set `state.authenticated = True`.

## Security requirements

- Never include command `0x6A` in safe payload capture.
- Never expose the pair key in diagnostics.
- Never expose a member token or account password in diagnostics or logs.
- Keep authentication payloads excluded even when adding more protocol-capture tooling.
- Redact other known device identifiers where diagnostics can expose them.

## Failure semantics

Authentication failures raise `DjiPowerAuthError` and cause connection setup to abort and clean up the current client. The outer connection loop handles retry/backoff.

Do not treat a successful GATT connection or notify subscription as authenticated readiness. The connection is ready only after authentication and initial configuration complete.
