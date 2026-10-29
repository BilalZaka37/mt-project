# MT Project v0.2 validation

Validation performed **29–30 October 2026, Asia/Karachi**. Results below distinguish real executed checks from supplied deployment artifacts. Earlier increment results are preserved in [v0.1 validation](VALIDATION-v0.1.md).

## Automated release suite

**39 passed, 1 skipped, 0 failed** in 47.93 seconds, with the actual YOLO integration enabled. The skipped test requires a running disposable PostgreSQL instance.

Executed coverage includes authentication/roles/revocation, source encryption, upload validation, polygon/class/cooldown rules, actual capture and H.264 encoding, protected/range media reads, continuous recording during slow/failed inference, bounded latest-frame behavior, pre/post-event clips, explicit partial windows and restart-interrupted clips, concurrent-camera capacity, reconnection/offline/recovered transitions, atomic event/outbox persistence, real HTTP failure then successful retry, HMAC verification, permanent/retry-exhausted failures, paused receivers/manual retries, expired-lease recovery, per-attempt outcomes, sample checksums/cleanup, v0.1 data preservation, retention, and self-hosted API documentation.

Most rule-boundary tests use deterministic detector fixtures. The opt-in vision test uses actual YOLO11n/ByteTrack on actual OpenCV pedestrian footage and decodes the resulting incident MP4. This is not a detection-accuracy benchmark.

## Running-application acceptance

The actual FastAPI application was exercised against a public recorded source and a loopback HTTP MJPEG replay of that source with deliberate disconnections. A separate local receiver verified signed alert payloads, deliberately rejected its first request with HTTP 503, then accepted the retry with HTTP 204.

| Measurement | Observed result |
| --- | --- |
| Fresh sample-source intrusion events in acceptance run | 12 |
| Accepted local alert deliveries at checkpoint | 14 |
| Network-source reconnections | 1 |
| Exported incident clip | 8.1 seconds, H.264 MP4 |
| Actual trigger offset in exported clip | 3.0 seconds |
| Partial coverage flag for selected clip | false |
| Exported independent recording | 9.9 seconds |
| Sample recorder drops | 0 |
| Retry outcome | HTTP 503 then HTTP 204, same delivery ID |

The delivery's recorded attempt trace is retained in the local application. The validation destination was paused after the run; it will not send in the background. The camera sources were stopped after acceptance. Exported MP4s were decoded using OpenCV. Source attribution remains visible in the app.

## Browser verification

- Compiled React interface loads against the actual authenticated API.
- Readiness shows independently measured capture, inference, recording, and reconnect state.
- Incident evidence shows the triggering object/zone/rule, source timestamp, snapshot, clip coverage, and trigger offset.
- The exported 8.1-second incident MP4 loaded in Chromium with readyState 4, dimensions 768×576, and no media error.
- Recording playback, alert delivery history, per-attempt inspection, and the public-footage import are included in browser QA; screenshots are supplied separately.

## Build and migration checks

TypeScript/Vite production build passed. Alembic upgraded the backed-up existing local database and `alembic check` reports no drift. Compose configuration is checked separately from a container run. The Windows launch scripts are syntax-checked. API health and the compiled interface return HTTP 200 during validation.

## Environment and provenance

Windows; Python 3.10.11; OpenCV 4.12.0; Ultralytics 8.3.228; PyTorch 2.9.1+cpu; torchvision 0.24.1+cpu; imageio-ffmpeg 0.6.0; YOLO11n with ByteTrack. PostgreSQL is configured for deployment but these executed tests use SQLite.

Footage: OpenCV public `samples/data/vtest.avi`, SHA-256 `45cddc9490be69345cbdab64ca583be65987e864ca408038e648db99e10516cf`. It is actual recorded video replayed for testing, not a physical camera or footage filmed by MT Project. Model weights are explicitly downloaded from official Ultralytics releases and remain outside the source archive.

## Remaining validation and limitations

- Physical RTSP cameras, vendor-specific codecs/credentials, actual camera networks, GPU/CUDA, sustained multi-camera load, disk exhaustion, and long-duration recovery remain unvalidated here.
- Docker Engine is not running on this host. Docker image build/run and PostgreSQL runtime remain pending; the CI workflow is authored but has not been claimed to have run remotely.
- No measured precision/recall, false-alarm rate, uptime SLA, lossless-recording guarantee, or production-security certification is claimed.
- This is a single-node, single-API-process implementation with bounded in-memory work. Distributed worker ownership, tenant/site isolation, encrypted object storage, cloud synchronization, audio, MFA/OIDC, and native email/SMS/WhatsApp adapters remain future increments.
- Clips interrupted by restart become failed; crash-left partial recordings are not automatically repaired. Uploaded sources/cache/active encoders and pending delivery backlogs are outside the finalized-media quota.

The suite emits one third-party test-client deprecation warning. The intentional invalid-MP4 upload emits an expected FFmpeg `moov atom` diagnostic; neither is a test failure.
