# MT Project

**Version 0.2.0 — video surveillance with independent recording, explainable incidents, and traceable alert delivery.**

MT Project is an original application built with React, FastAPI, OpenCV, YOLO11/ByteTrack, FFmpeg, and PostgreSQL (SQLite for local development). It processes real video; camera status, detections, evidence, and delivery results are never fabricated. Third-party libraries and public test footage are credited separately from the application code.

## Portfolio website

The static portfolio page in [docs/index.html](docs/index.html) includes an actual 87-second browser workflow recording. It demonstrates detection, incident review and acknowledgement, stored-video playback, and persisted webhook retry history using public validation footage. See [GitHub Pages publishing instructions](docs/PUBLISHING.md). The portfolio website presents recorded evidence; the complete FastAPI application runs separately using the instructions below.

## Try it without your own camera or recording

After signing in, select **Add camera → Use public footage**. MT Project retrieves a checksum-verified pedestrian recording from OpenCV's public sample repository and creates a source with an editable restricted zone. Press **Start**. Detection uses your configured YOLO model, and the source is clearly labelled as public recorded validation footage.

Open a camera to inspect capture, recording, detection, skipped inference frames, dropped recording frames, and reconnection history. Open **Event history → Review evidence** for a snapshot, rule explanation, and pre/post-event MP4. Use **Recordings → Play** for continuous segments. **Alert delivery** shows destination configuration and persistent delivery attempts.

The public recording can also be downloaded in advance:

```text
cd backend
python scripts/download_sample.py
```

It is not a physical-camera test, footage filmed by MT Project, or a labelled accuracy benchmark. Internet is required only to retrieve it; subsequent imports use the verified local cache.

## What works

- Multiple RTSP and HTTP(S) video sources, plus uploaded MP4, AVI, MOV, MKV, and WebM that OpenCV can decode.
- **Independent capture, recording, and inference.** A bounded recorder queue receives captured JPEG packets; inference consumes the latest available frame. Slow or failed inference does not block recording. Recording overload is reported through a dropped-frame counter.
- Per-camera YOLO11/ByteTrack state, actual annotated monitoring frames, stale-frame rejection, normalized polygon zones, class filtering, and ground-point entry events with cooldowns.
- **H.264 MP4 recordings**, unannotated by inference, at 10 FPS output. Thirty-second segments finalize automatically or when a source stops/disconnects. Existing v0.1 AVI recordings remain downloadable.
- **Incident clips** with configurable pre/post windows (default 3 seconds before and 5 after), raw captured video, a trigger offset, and explicit partial-window/failed/expired states. Snapshot evidence remains independently available.
- Stream reconnection with backoff until stopped; deduplicated offline/recovered health events. Uploaded files complete at EOF without looping.
- **Persistent signed webhooks:** event and outbox record commit together; retries survive restart; leased claims recover; delivery IDs remain stable across attempts; permanent or exhausted failures remain visible and can be retried manually.
- Argon2 password hashes, hashed 12-hour HttpOnly sessions, revocation, same-origin write protection, workspace roles, audit records, encrypted camera URLs and webhook secrets, and authenticated media downloads/playback.
- Alembic upgrades that preserve v0.1 data, PostgreSQL Compose configuration, a non-root CPU image, finalized-evidence age/quota retention, and automated tests.

## Start on this prepared workspace

The separate **Start MT Project.ps1** launcher uses the already-installed workspace runtime and downloaded weights. Local access details are supplied separately from the source archive. The test server is stopped after verification; use that launcher to start it again.

## Portable Windows setup

Requirements: Python **3.10 or 3.11**, Node.js **22+**, npm, and internet for initial packages/weights. Inside this project directory:

```powershell
.\scripts\Start-Local.ps1 -Setup -Email you@example.com -DownloadModel -DownloadSample
```

The script creates `.venv`, installs dependencies, builds React, migrates SQLite, asks you to choose an administrator password, explicitly downloads trusted model weights and public sample footage, then starts **http://127.0.0.1:8000**.

Later runs:

```powershell
.\scripts\Start-Local.ps1
```

There is no default password or public account-registration endpoint. Existing installations should omit `-Email` unless creating another administrator. Stop the application before upgrading dependencies or migrating an existing database; back up its database, media, and encryption key first.

## Manual setup

```text
python -m venv .venv
# Activate .venv using your shell's activation command.
python -m pip install -r backend/requirements-vision.txt
cd frontend
npm ci
npm run build
cd ../backend
alembic upgrade head
python -m app.cli create-admin --email you@example.com
python scripts/download_model.py
python scripts/download_sample.py
# Set MT_MODEL_PATH to the absolute local model path printed above.
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

For monitoring/recording without YOLO, install `backend/requirements.txt` and disable detection. Missing or failed detection is shown explicitly while capture and recording continue. The packaged FFmpeg dependency provides an encoder; no separate terminal FFmpeg install is required on supported wheel platforms.

For frontend development, run `npm run dev` in `frontend` while the API runs on port 8000. The Vite proxy preserves same-origin API behavior.

## Docker with PostgreSQL

Docker Engine must be running. Copy `.env.example` to `.env` and set a random URL-safe `MT_DB_PASSWORD` and a Fernet `MT_ENCRYPTION_KEY`:

```text
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up --build -d
docker compose exec app python -m app.cli create-admin --email you@example.com
docker compose exec app python scripts/download_model.py
docker compose exec app python scripts/download_sample.py
```

The service binds to loopback port 8000, PostgreSQL stays inside the Compose network, and persistent named volumes hold database/media. Use **one API process/replica**: camera ownership and media buffers remain process-local. Docker/PostgreSQL runtime validation is still required on the target host; Compose syntax validation alone does not establish it.

For remote access, configure HTTPS, trusted proxy scheme/Host handling, secure cookies, network restrictions, storage limits, backup/restore, and target-site validation. The default Uvicorn command deliberately ignores forwarding headers. See [architecture and boundaries](docs/ARCHITECTURE.md).

## Alert delivery

An administrator can connect a generic webhook receiver from **Alert delivery**. Set `MT_WEBHOOK_ALLOWED_HOSTS` to an explicit comma-separated hostname allowlist first. HTTPS is required; development loopback HTTP additionally requires `MT_ALLOW_LOCAL_WEBHOOKS=true`. Credentials, query parameters, and fragments are rejected in destination URLs. Store receiver authentication in the signing secret rather than the URL.

The receiver accepts the MT Project JSON schema, verifies the HMAC signature, and deduplicates the stable delivery ID. Existing events are not retroactively sent. Pausing a destination prevents new claims; an already in-flight request can finish. Pending records remain for resumption. Delivery is **at least once**, not exactly once. A 2xx response confirms receiver acceptance, not that a person read an alert.

See [webhook contract and local validation](docs/ALERT_DELIVERY.md). Native email, SMS, and WhatsApp adapters are not implemented; they require a configured provider/receiver and credentials. No external messages are sent by the sample workflow.

## Configuration

Python reads environment variables at startup. Compose reads `.env`; local Python does not automatically load it.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MT_DATABASE_URL` | SQLite under data directory | PostgreSQL URL uses `postgresql+psycopg://...` |
| `MT_DATA_DIR` | `data` under backend working directory | Media, sample cache, local DB, fallback encryption key |
| `MT_ENCRYPTION_KEY` | Persisted local Fernet key | Required in Compose; preserve for source/receiver decryption |
| `MT_MODEL_PATH` | Unset | Trusted local YOLO weights; no automatic worker-time downloads |
| `MT_DEVICE` | `cpu` | GPU needs a compatible separately validated CUDA deployment |
| `MT_SECURE_COOKIE` | `false` | Enable with correctly configured HTTPS |
| `MT_MAX_CAMERAS` | `8` | Worker cap, not a performance guarantee |
| `MT_UPLOAD_MB` | `512` | Per-upload limit |
| `MT_SEGMENT_SECONDS` | `30` | Recording segment length, 1–300 seconds |
| `MT_CLIP_PRE_SECONDS` | `3` | Incident pre-buffer, 0–10 seconds |
| `MT_CLIP_POST_SECONDS` | `5` | Incident post-window, 0–15 seconds |
| `MT_RETENTION_DAYS` | `7` | Event/finalized media age retention |
| `MT_MEDIA_QUOTA_MB` | `10240` | Finalized snapshot/clip/recording quota |
| `MT_WEBHOOK_ALLOWED_HOSTS` | Empty | Explicitly allowed receiver hostnames |
| `MT_ALLOW_LOCAL_WEBHOOKS` | `false` | Allow HTTP only for loopback validation |
| `MT_ALERT_RETRY_SECONDS` | `5` | Initial retry delay; exponential backoff |

Finalized evidence is checked every minute. Source uploads, cached samples, active segments, the database, and crash-left partial files are outside that quota; use filesystem/proxy limits for production. Quota eviction can remove media while retaining its event metadata. A server restart marks incomplete incident clips as failed; in-memory pre/post buffers cannot be recovered. Partial `.mp4.part` recordings are not exposed as complete evidence.

On Windows, protect data and key files with appropriate NTFS ACLs. Back up the database, encryption key, and media together. Deleting a camera permanently deletes its events, clips, snapshots, recordings, and uploaded source. The shared public-sample cache remains for reuse.

## Tests and API

```text
cd backend
python -m pip install -r requirements-test.txt
python -m pytest -q
```

Opt into real YOLO integration:

```powershell
$env:MT_TEST_MODEL = 'C:\absolute\path\yolo11n.pt'
$env:MT_TEST_VIDEO = 'C:\absolute\path\pedestrians.avi'
python -m pytest -q -s
```

The default suite has deterministic detector fixtures alongside real capture/encoding/database/network tests. The opt-in vision test uses actual YOLO and recorded pedestrians. The separate PostgreSQL smoke test requires a disposable database named `mt_project_ci` via `MT_TEST_POSTGRES_URL`. The supplied GitHub Actions workflow has not been represented as having run remotely.

Self-hosted interactive OpenAPI: **http://127.0.0.1:8000/docs**. Sign in through the app first; the documentation includes the required protection header on writes. APIs cover authentication, camera CRUD/control, sample import, zones, event filters/acknowledgement, incident clips, recording playback/downloads, alert destinations/deliveries/retries, users, system status, and audit records. All media requires a valid session.

See [executed validation](docs/VALIDATION.md), [architecture](docs/ARCHITECTURE.md), and [third-party notices](docs/THIRD_PARTY.md). This is an engineering foundation with real functionality. Physical RTSP devices, GPU performance, sustained capacity, PostgreSQL/Docker operation, detection accuracy, and production security remain target-deployment validation tasks.
