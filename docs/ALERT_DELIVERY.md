# MT Project alert delivery contract

## Receiver setup

Configure `MT_WEBHOOK_ALLOWED_HOSTS=receiver.example` on the server, restart it, then add the HTTPS receiver in **Alert delivery** as an administrator. Supply a shared signing secret of at least 32 characters. Secrets are encrypted and never returned by list/create responses. Selected event kinds are intrusion, detection, snapshot, offline, and recovered. Only new matching events create deliveries.

The receiver must accept the MT Project schema. A Slack/WhatsApp/provider webhook with a different required payload is not automatically compatible; use an adapter that verifies this contract and translates it to the selected service. No provider account or external message destination is preconfigured.

## Request verification

- `Content-Type: application/json`
- `X-MT-Delivery`: immutable delivery ID; use it as an idempotency key.
- `X-MT-Timestamp`: Unix timestamp in seconds for this attempt.
- `X-MT-Signature`: `sha256=` followed by hexadecimal HMAC-SHA256.

The signed bytes are `timestamp + "." + raw_request_body`, using the shared secret as the HMAC key. Verify the raw bytes before parsing/reformatting JSON, compare signatures in constant time, reject timestamps outside a reasonable window, and persist delivery IDs to avoid repeating side effects. Each retry has the same delivery ID/body and a fresh timestamp/signature.

```python
expected = 'sha256=' + hmac.new(
    secret.encode(), timestamp.encode() + b'.' + body, hashlib.sha256
).hexdigest()
valid = hmac.compare_digest(received_signature, expected)
```

The payload contains `product: "MT Project"`, schema version, delivery ID, and an event object with camera name/ID, kind, object/zone/track/confidence, capture timestamp, rule details, and relative snapshot/evidence paths where applicable. These media paths still require authenticated application access; webhook signing does not grant unrestricted media access. A receiver can construct user-facing links using the configured deployment URL.

## Persistence and retries

The event and outbox entry commit atomically. Due records are claimed with a 60-second lease. An interrupted sending record becomes eligible again after the lease expires. The receiver must therefore tolerate duplicates even if an earlier request succeeded but its acknowledgement was lost.

Per-attempt journal records preserve timestamps, HTTP status, and errors. If a lease expires before an outcome is persisted, the previous attempt is marked unknown instead of being labelled as a confirmed failure. Manual retry starts a fresh retry budget while retaining earlier journal records. Deliveries created before the journal migration retain their counters/results; no historical attempt records are invented.

Any 2xx response marks delivery accepted. Network errors, 5xx, redirects, and HTTP 408/425/429 retry with exponential delays: default 5, 10, 20, 40, 80 seconds before the next failed attempt, stopping after six failed attempts. Other 4xx responses are permanent failures. `Retry-After` is not implemented in this increment. Dead deliveries remain inspectable and operators can explicitly retry them. This does not establish that a human received or read a downstream notification.

Pausing an endpoint stops new claims. Pending retries remain stored; an already in-flight request may finish. Matching events occurring while an endpoint is paused do not create new deliveries for it. Resuming processes its retained backlog. Old completed/dead records follow retention; paused pending backlogs require operator management.

## Reproduce locally without sending external messages

Start a loopback receiver in one terminal with the same secret configured in the app:

```powershell
cd backend
$env:MT_RECEIVER_SECRET = '<choose-at-least-32-random-characters>'
python scripts/validation_receiver.py --fail-first 1
```

Start the app in another terminal with:

```powershell
$env:MT_WEBHOOK_ALLOWED_HOSTS = '127.0.0.1'
$env:MT_ALLOW_LOCAL_WEBHOOKS = 'true'
$env:MT_ALERT_RETRY_SECONDS = '1'
# Start the app using the usual launcher with these variables inherited.
```

Connect `http://127.0.0.1:8790/events` in **Alert delivery**, using the same secret. Import/start public test footage to generate real YOLO intrusions. The receiver deliberately returns 503 on its first valid request, then 204. The delivery ledger shows retry and accepted states. Its JSONL log records verification outcomes and accepted delivery IDs; protect/delete that test log as appropriate. Stop or pause the destination after the test.

To test network recovery using actual footage over HTTP:

```text
cd backend
python scripts/validation_camera.py --disconnect-after 8
```

Add `http://127.0.0.1:8791/stream.mjpg` as a camera and label it as a **public-recording network fixture**. It streams real sample frames and deliberately closes the connection every eight seconds. MT Project records offline/recovered transitions and reconnects. This validates the local HTTP failure path; physical RTSP cameras and real network conditions remain separate acceptance tests.
