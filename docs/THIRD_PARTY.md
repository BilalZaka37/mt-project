# MT Project third-party notices

MT Project application source is original. Dependency licenses remain those of their respective authors; no blanket commercial licensing claim is made.

Primary dependencies include FastAPI, Uvicorn, SQLAlchemy, Alembic, Psycopg, OpenCV, NumPy, cryptography, pwdlib/Argon2, PyTorch, torchvision, Ultralytics, lap, React, Vite, TypeScript, and Lucide. Consult installed distributions and upstream repositories for complete license texts and transitive dependencies.

- YOLO implementation, tracker integration, and optional weights: [Ultralytics repository](https://github.com/ultralytics/ultralytics), [tracking documentation](https://docs.ultralytics.com/modes/track/), and [licensing](https://www.ultralytics.com/license). Review the applicable open-source or enterprise terms before distribution/deployment. Weights are downloaded explicitly from official releases and are excluded from the source archive.
- Pedestrian validation footage: [OpenCV `samples/data/vtest.avi`](https://github.com/opencv/opencv/blob/master/samples/data/vtest.avi). Used only for development validation; not represented as footage from a connected physical camera. The source archive does not bundle it.
- Authentication design reference: [FastAPI security documentation](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/). MT Project uses opaque revocable sessions instead of JWTs.
- Icons: [Lucide](https://lucide.dev/), supplied by the `lucide-react` dependency. The interface uses original layouts, CSS, and copy.
- Self-hosted API documentation: [Swagger UI](https://github.com/swagger-api/swagger-ui), version 5.30.2 from the official `swagger-ui-dist` npm package. Its license and notice are included beside the bundled documentation assets.
- MP4 encoder discovery: [`imageio-ffmpeg`](https://github.com/imageio/imageio-ffmpeg), version 0.6.0, with platform-packaged FFmpeg binaries. The wrapper and the bundled FFmpeg build have their own respective licensing terms. Inspect the exact binary's configuration/license before redistribution; no proprietary ownership of FFmpeg or its codecs is claimed.

The optional sample downloader uses OpenCV's public `vtest.avi` recording and verifies SHA-256 `45cddc9490be69345cbdab64ca583be65987e864ca408038e648db99e10516cf`. The sample, HTTP replay, and exported validation clips are explicitly labelled as public validation footage. They are not footage filmed by MT Project and do not provide a labelled accuracy benchmark. The source archive excludes the recording and generated media; the downloader and provenance metadata are included.

Before a production release, generate a complete dependency SBOM, run dependency/security review, and complete the applicable third-party notices for the exact locked deployment artifact.
