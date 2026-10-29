# MT Project validation record

Executed locally on **29 October 2026 (Asia/Karachi)**. This record distinguishes executed checks from supplied deployment artifacts.

## Executed and passed

| Check | Result |
| --- | --- |
| Backend full integration/rules suite, with real vision enabled | **22 passed** in 22.14 seconds |
| Additional concurrent-camera/capacity integration test | **1 passed** in 3.33 seconds; PostgreSQL-only test skipped locally |
| Self-hosted API documentation | **1 passed** in 0.74 seconds; verifies local assets, CSP nonce, protection header, and OpenAPI branding |
| Real CPU YOLO11n / ByteTrack pipeline | **7 tracked-person zone-entry events**, JPEG evidence retrieved, one finalized recording retrieved |
| Real footage input | First 35 frames of OpenCV's public pedestrian video, encoded as a short test clip at 10 FPS |
| Recording timing regression | 60 frames at 30 FPS produced approximately 2 seconds at the recorder's 10 FPS output rate |
| Two simultaneous video workers | Separate runtime instances and camera-scoped events; worker capacity rejection verified |
| React production build | TypeScript compilation and Vite build passed |
| Database migrations | Alembic initial migration executed; `alembic check` reports no schema drift on SQLite |
| Compose configuration | `docker compose config --quiet` passed with temporary validation environment values |
| Python package consistency | `pip check`: no broken requirements |
| PowerShell startup script | Parsed successfully with the PowerShell language parser |
| Local application | API health and compiled React root both returned HTTP 200 |

The **24 passing tests** were executed across the full run and subsequent additional-camera and API-documentation checks. The opt-in PostgreSQL test was not executed against a running PostgreSQL server on this machine.

The full suite covers authentication, HttpOnly-session behavior, CSRF/origin protection, expiry, logout/password revocation, account deactivation, administrator/operator/viewer boundaries, duplicate users, source encryption, source URL validation, uploads and limits, actual OpenCV capture/encoding, polygon validation, boundary/class/cooldown semantics, snapshots, event filtering/acknowledgement, protected media, deletion cleanup, evidence retention, and quota eviction. Most rule tests use an explicit deterministic detector fixture; the vision test uses the actual YOLO implementation and real footage.

One third-party test-client deprecation warning was emitted (`anyio.abc.BlockingPortal`). The intentionally invalid MP4 upload also produces an expected FFmpeg diagnostic about a missing `moov` atom. These did not cause test failures.

## Browser workflow exercised

The local compiled application was opened in the in-app browser. The following actions completed through the UI:

1. Signed in with the generated local administrator account.
2. Uploaded the actual OpenCV pedestrian video and enabled recording.
3. Started the source; verified real annotated frames, tracking IDs, changing object counts, processing FPS, and persisted detections.
4. Opened the camera, drew a four-corner restricted zone, and saved it.
5. Captured a manual snapshot and observed actual person intrusion events for the saved zone.
6. Acknowledged an intrusion, filtered to acknowledged events, and verified the persisted Reviewed status.
7. Opened JPEG evidence in the snapshot viewer. Screenshot artifacts are supplied separately from the source archive.
8. Opened the final self-hosted API documentation and verified that its schema and operation controls render in the browser.

Browser footage is labelled **Pedestrian validation · OpenCV footage**. It is recorded validation video, not a physical camera connection. The detector's predictions include imperfect class assignments; no precision/recall or site-specific safety claim is made from this sample.

## Tested environment

- Windows, Python 3.10.11; Node.js 24.12.0.
- FastAPI 0.121.3; SQLAlchemy 2.0.44; SQLite for executed persistence tests.
- OpenCV 4.12.0; Ultralytics 8.3.228; PyTorch 2.9.1+cpu; torchvision 0.24.1+cpu; ByteTrack.
- YOLO11n weights SHA-256: `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`.

## Not validated here

- Physical RTSP/IP cameras, device-specific credentials/codecs, camera time synchronization, and network interruption behavior on actual devices.
- Sustained fleet throughput, GPU/CUDA inference, worst-case memory, frame drop/latency, disk exhaustion, and long-duration recovery.
- Docker image build/run and PostgreSQL runtime: Docker CLI is installed, but the Docker Engine is not running. Compose syntax alone does not validate a container deployment.
- The supplied GitHub Actions workflow and PostgreSQL-only smoke test require execution in CI. They are authored, not represented as having passed remotely.
- Target-site detection accuracy, false alarm rates, adversarial inputs, penetration testing, TLS/proxy configuration, backup/restore, and production readiness.
- Cloud/on-premises/hybrid multi-node operation. This release is a single-node implementation; distributed and tenant-isolated deployment requires the next architecture increments.

Browser-compatible H.264 recording playback, audio, notification delivery, OIDC/MFA, per-camera ACLs, multi-tenancy, and distributed workers are not implemented. Recordings are downloadable MJPEG AVI files.
