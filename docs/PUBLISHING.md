# MT Project on GitHub

The repository contains the full application and a static portfolio website in `docs/`. The website presents genuine application evidence, including the 87.4-second captioned workflow recording. GitHub Pages does not host FastAPI, PostgreSQL, camera workers, or live inference.

## GitHub Pages

1. Push the sanitized source to the `main` branch of the public `mt-project` repository.
2. Open repository **Settings → Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**.
4. Select **main**, choose **/docs**, and save.
5. Wait for the Pages deployment to succeed, then open the URL shown by GitHub. Do not represent the website as published until that result is confirmed.

The page uses relative assets so it works under the repository URL. No JavaScript framework build, API key, third-party analytics, or external font service is required. Repository links currently target the connected GitHub account `BilalZaka37/mt-project`; update them if publishing elsewhere.

## Included evidence

- `assets/mt-project-workflow.mp4`: actual edited browser screen recording, 87.4 seconds, H.264, silent with captions. It joins four capture sections at page transitions and masks the account label.
- The live monitoring section shows actual YOLO11n/ByteTrack output. Incident and recording playback use raw captured video.
- The webhook journal shows an earlier local HTTP 503 → 204 test. It is not a provider delivery generated during the screen recording.
- Public source: [OpenCV vtest.avi](https://github.com/opencv/opencv/blob/4.x/samples/data/vtest.avi). See [third-party notices](THIRD_PARTY.md).

## Publication exclusions

Do not publish `.env`, local credentials, databases, session records, source uploads, runtime media folders, encryption keys, model weights, dependency folders, or machine-local launch/access files. Only the explicitly selected portfolio media under `docs/assets/` belongs in this repository.

The application's local and Docker setup instructions remain in [README](../README.md). Target-host production validation is separate from publishing this portfolio website.
