import asyncio
import logging
import secrets
import shutil
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import cv2
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .alerts import AlertDispatcher, enqueue_event
from .alert_routes import register_alert_routes
from .samples import fetch_sample, PROVENANCE
from .db import Audit, Base, Camera, Event, Recording, Session, User, Zone, connect, utcnow
from .pipeline import CameraManager
from .schemas import CameraInput, CameraUpdate, Login, NewUser, PasswordChange, ZoneInput
from .security import DUMMY_HASH, cipher, issue_session, passwords, token_hash

log = logging.getLogger('mt-project')


def create_app(settings=None, detector_factory=None):
    settings = settings or Settings()
    engine, sessions = connect(settings.database_url)
    encryption = cipher(settings)
    kwargs = {'detector_factory': detector_factory} if detector_factory else {}
    manager = CameraManager(settings, sessions, encryption, **kwargs)
    dispatcher = AlertDispatcher(settings, sessions, encryption)
    mutation_lock = threading.Lock()
    attempts = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app):
        # The initial schema is applied by Alembic before starting the service.
        with sessions() as db:
            db.execute(select(User).limit(1))
        manager.resume()
        dispatcher.start()
        yield
        manager.close()
        dispatcher.close()
        engine.dispose()

    app = FastAPI(title='MT Project', version='0.2.0', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.sessions, app.state.manager, app.state.settings = sessions, manager, settings
    app.state.engine, app.state.cipher = engine, encryption
    app.state.dispatcher = dispatcher

    @app.middleware('http')
    async def protections(request: Request, call_next):
        if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('x-mt-request') != '1':
                return Response('Missing X-MT-Request header', status_code=403)
            origin = request.headers.get('origin')
            if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
                return Response('Cross-origin request denied', status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if 'Content-Security-Policy' not in response.headers:
            response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def db_session():
        with sessions() as db:
            yield db

    def current_user(request: Request, db=Depends(db_session)):
        token = request.cookies.get('mt_session', '')
        session = db.get(Session, token_hash(token))
        if not session:
            raise HTTPException(401, 'Sign in to MT Project')
        expiry = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
        user = db.get(User, session.user_id)
        if expiry < utcnow() or not user or not user.active:
            raise HTTPException(401, 'Session expired')
        return user

    def roles(*allowed):
        def check(user=Depends(current_user)):
            if user.role not in allowed:
                raise HTTPException(403, 'Insufficient permissions')
            return user
        return check

    admin = roles('admin')
    operator = roles('admin', 'operator')

    def audit(db, user, action, target):
        db.add(Audit(user_id=user.id, action=action, target=str(target)))

    def get_camera(db, camera_id):
        camera = db.get(Camera, camera_id)
        if not camera:
            raise HTTPException(404, 'Camera not found')
        return camera

    def camera_dict(camera):
        return {'id': camera.id, 'name': camera.name, 'location': camera.location, 'kind': camera.kind,
                'enabled': camera.enabled, 'detection_enabled': camera.detection_enabled,
                'recording_enabled': camera.recording_enabled, 'confidence': camera.confidence,
                'provenance':camera.provenance,
                **manager.state(camera.id)}

    def event_dict(event, name):
        return {'id': event.id, 'camera_id': event.camera_id, 'camera_name': name, 'kind': event.kind,
                'label': event.label, 'confidence': event.confidence, 'track_id': event.track_id,
                'zone_name': event.zone_name, 'acknowledged': event.acknowledged,
                'snapshot_url': f'/api/events/{event.id}/snapshot' if event.snapshot else None,
                'details':event.details,'clip_status':event.clip_status,
                'clip_url':f'/api/events/{event.id}/clip' if event.clip_filename and event.clip_status=='ready' else None,
                'clip_duration':event.clip_duration,'clip_offset':event.clip_offset,
                'clip_truncated':event.clip_truncated,'clip_error':event.clip_error,
                'created_at': event.created_at}

    register_alert_routes(app,settings,encryption,db_session,admin,operator,audit)

    docs_assets = Path(__file__).parent/'static'/'docs'
    app.mount('/docs-assets', StaticFiles(directory=docs_assets), name='MT Project API documentation assets')

    @app.get('/docs', include_in_schema=False)
    def documentation():
        nonce = secrets.token_urlsafe(24)
        html = get_swagger_ui_html(openapi_url='/openapi.json', title='MT Project API',
                                  swagger_js_url='/docs-assets/swagger-ui-bundle.js',
                                  swagger_css_url='/docs-assets/swagger-ui.css',
                                  swagger_favicon_url='/docs-assets/favicon.svg').body.decode()
        html = html.replace('<script>', f'<script nonce="{nonce}">')
        html = html.replace('const ui = SwaggerUIBundle({', "const ui = SwaggerUIBundle({\nrequestInterceptor: (request) => { request.headers['X-MT-Request'] = '1'; return request; },")
        return HTMLResponse(html, headers={'Content-Security-Policy': f"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'nonce-{nonce}'; connect-src 'self'; frame-ancestors 'none'"})

    @app.get('/api/health')
    def health(db=Depends(db_session)):
        db.execute(select(1))
        return {'product': 'MT Project', 'status': 'ok', 'version': '0.2.0'}

    @app.post('/api/auth/login')
    def login(payload: Login, request: Request, response: Response, db=Depends(db_session)):
        key = request.client.host if request.client else 'local'
        now = time.monotonic()
        with mutation_lock:
            # Bounded single-process limiter. Proxy headers are deliberately not trusted.
            for address in list(attempts):
                if not attempts[address] or now-attempts[address][-1] > 300:
                    del attempts[address]
            queue = attempts[key]
            while queue and now-queue[0] > 300:
                queue.popleft()
            if len(queue) >= 10:
                raise HTTPException(429, 'Too many login attempts. Retry in five minutes.')
            queue.append(now)
        user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
        valid = passwords.verify(payload.password, user.password_hash if user else DUMMY_HASH)
        if not valid or not user or not user.active:
            raise HTTPException(401, 'Invalid email or password')
        token = issue_session(db, user)
        audit(db, user, 'auth.login', user.id)
        db.commit()
        response.set_cookie('mt_session', token, httponly=True, secure=settings.secure_cookie,
                            samesite='strict', max_age=43200, path='/')
        return {'id': user.id, 'email': user.email, 'role': user.role}

    @app.get('/api/auth/me')
    def me(user=Depends(current_user)):
        return {'id': user.id, 'email': user.email, 'role': user.role}

    @app.post('/api/auth/logout', status_code=204)
    def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(db_session)):
        db.execute(delete(Session).where(Session.token_hash == token_hash(request.cookies.get('mt_session', ''))))
        db.commit()
        response.delete_cookie('mt_session', path='/')

    @app.post('/api/auth/password', status_code=204)
    def change_password(payload: PasswordChange, response: Response, user=Depends(current_user), db=Depends(db_session)):
        if not passwords.verify(payload.current_password, user.password_hash):
            raise HTTPException(400, 'Current password is incorrect')
        user.password_hash = passwords.hash(payload.new_password)
        db.execute(delete(Session).where(Session.user_id == user.id))
        audit(db, user, 'auth.password_changed', user.id)
        db.commit()
        response.delete_cookie('mt_session', path='/')

    @app.get('/api/users')
    def list_users(user=Depends(admin), db=Depends(db_session)):
        return [{'id': u.id, 'email': u.email, 'role': u.role, 'active': u.active} for u in db.scalars(select(User))]

    @app.post('/api/users', status_code=201)
    def add_user(payload: NewUser, user=Depends(admin), db=Depends(db_session)):
        new = User(email=payload.email, password_hash=passwords.hash(payload.password), role=payload.role)
        db.add(new)
        audit(db, user, 'user.created', payload.email)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'User already exists')
        return {'id': new.id, 'email': new.email, 'role': new.role}

    @app.post('/api/users/{user_id}/deactivate', status_code=204)
    def deactivate(user_id: int, user=Depends(admin), db=Depends(db_session)):
        if user_id == user.id:
            raise HTTPException(400, 'You cannot deactivate your own account')
        target = db.get(User, user_id)
        if not target:
            raise HTTPException(404, 'User not found')
        target.active = False
        db.execute(delete(Session).where(Session.user_id == user_id))
        audit(db, user, 'user.deactivated', user_id)
        db.commit()

    @app.get('/api/cameras')
    def cameras(user=Depends(current_user), db=Depends(db_session)):
        return [camera_dict(c) for c in db.scalars(select(Camera).order_by(Camera.id))]

    @app.post('/api/cameras', status_code=201)
    def add_camera(payload: CameraInput, user=Depends(admin), db=Depends(db_session)):
        camera = Camera(name=payload.name.strip(), location=payload.location, kind='stream',
                        source_encrypted=encryption.encrypt(payload.source.encode()).decode(),
                        detection_enabled=payload.detection_enabled, recording_enabled=payload.recording_enabled,
                        confidence=payload.confidence)
        db.add(camera)
        db.flush()
        audit(db, user, 'camera.created', camera.id)
        db.commit()
        return camera_dict(camera)

    @app.post('/api/cameras/sample',status_code=201)
    def import_sample(user=Depends(admin),db=Depends(db_session)):
        try:
            source=fetch_sample(settings)
        except Exception:
            log.exception('Public validation footage download failed')
            raise HTTPException(503,'Unable to retrieve public test footage. Run scripts/download_sample.py or check server connectivity.')
        camera=Camera(name='Walkway validation',location='Public recorded footage · OpenCV',kind='file',
            source_encrypted=encryption.encrypt(str(source).encode()).decode(),confidence=.35,
            recording_enabled=True,provenance=PROVENANCE)
        db.add(camera)
        db.flush()
        db.add(Zone(camera_id=camera.id,name='Walkway boundary',classes=['person'],
            points=[[.15,.35],[.95,.35],[.95,.9],[.15,.75]]))
        audit(db,user,'sample.imported',camera.id)
        db.commit()
        return camera_dict(camera)

    @app.post('/api/cameras/upload', status_code=201)
    def upload_camera(name: str = Form(..., min_length=1, max_length=100),
                      file: UploadFile = File(...), user=Depends(admin), db=Depends(db_session)):
        suffix = Path(file.filename or '').suffix.lower()
        if suffix not in ('.mp4', '.avi', '.mov', '.mkv', '.webm'):
            raise HTTPException(400, 'Upload an MP4, AVI, MOV, MKV, or WebM video')
        path = settings.data_dir/'uploads'/(uuid.uuid4().hex + suffix)
        size = 0
        try:
            with path.open('wb') as output:
                while chunk := file.file.read(1024*1024):
                    size += len(chunk)
                    if size > settings.upload_limit:
                        raise HTTPException(413, 'Video exceeds upload size limit')
                    output.write(chunk)
            cap = cv2.VideoCapture(str(path))
            try:
                valid, frame = cap.read()
            finally:
                cap.release()
            if not valid or frame is None:
                raise HTTPException(400, 'File does not contain a decodable video')
            camera = Camera(name=name.strip(), location='Uploaded video', kind='file',
                            source_encrypted=encryption.encrypt(str(path).encode()).decode())
            db.add(camera)
            db.flush()
            audit(db, user, 'video.uploaded', camera.id)
            db.commit()
            return camera_dict(camera)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()

    @app.put('/api/cameras/{camera_id}')
    def edit_camera(camera_id: int, payload: CameraUpdate, user=Depends(admin), db=Depends(db_session)):
        camera = get_camera(db, camera_id)
        if camera.enabled or manager.state(camera_id)['status'] in ('online','connecting','reconnecting'):
            raise HTTPException(409, 'Stop the camera before changing its configuration')
        for key, value in payload.model_dump().items():
            setattr(camera, key, value)
        audit(db, user, 'camera.updated', camera.id)
        db.commit()
        return camera_dict(camera)

    @app.post('/api/cameras/{camera_id}/start')
    def start_camera(camera_id: int, user=Depends(operator), db=Depends(db_session)):
        camera = get_camera(db, camera_id)
        with mutation_lock:
            try:
                manager.start(camera_id)
            except RuntimeError as exc:
                raise HTTPException(409, str(exc))
            camera.enabled = True
            audit(db, user, 'camera.started', camera_id)
            db.commit()
        return camera_dict(camera)

    @app.post('/api/cameras/{camera_id}/stop')
    def stop_camera(camera_id: int, user=Depends(operator), db=Depends(db_session)):
        camera = get_camera(db, camera_id)
        manager.stop(camera_id)
        camera.enabled = False
        audit(db, user, 'camera.stopped', camera_id)
        db.commit()
        return camera_dict(camera)

    @app.delete('/api/cameras/{camera_id}', status_code=204)
    def remove_camera(camera_id: int, user=Depends(admin), db=Depends(db_session)):
        camera = get_camera(db, camera_id)
        state = manager.runtimes.get(camera_id)
        if state and state.thread.is_alive():
            raise HTTPException(409, 'Stop the camera and wait for its worker to finish before deleting')
        for event in db.scalars(select(Event).where(Event.camera_id == camera_id)):
            if event.snapshot:
                (settings.data_dir/'snapshots'/event.snapshot).unlink(missing_ok=True)
            if event.clip_filename:
                (settings.data_dir/'clips'/event.clip_filename).unlink(missing_ok=True)
        for recording in db.scalars(select(Recording).where(Recording.camera_id == camera_id)):
            (settings.data_dir/'recordings'/recording.filename).unlink(missing_ok=True)
        if camera.kind == 'file':
            path = Path(encryption.decrypt(camera.source_encrypted.encode()).decode())
            if path.parent == settings.data_dir/'uploads':
                path.unlink(missing_ok=True)
        audit(db, user, 'camera.deleted', camera_id)
        db.delete(camera)
        db.commit()

    @app.get('/api/cameras/{camera_id}/frame')
    def frame(camera_id: int, user=Depends(current_user), db=Depends(db_session)):
        get_camera(db, camera_id)
        jpeg = manager.jpeg(camera_id)
        if not jpeg:
            raise HTTPException(503, 'No fresh camera frame available')
        return Response(jpeg, media_type='image/jpeg')

    @app.get('/api/cameras/{camera_id}/live')
    async def live(camera_id: int, request: Request, user=Depends(current_user)):
        with sessions() as db:
            get_camera(db, camera_id)
        async def frames():
            started = time.monotonic()
            while not await request.is_disconnected() and time.monotonic()-started < 60:
                jpeg = manager.jpeg(camera_id)
                if jpeg:
                    yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
                await asyncio.sleep(.15)
        # Connections last at most 60s; reconnect revalidates session and access.
        return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame')

    @app.post('/api/cameras/{camera_id}/snapshot', status_code=201)
    def snapshot(camera_id: int, user=Depends(operator), db=Depends(db_session)):
        camera = get_camera(db, camera_id)
        jpeg = manager.jpeg(camera_id)
        if not jpeg:
            raise HTTPException(409, 'Start the camera and wait for a live frame')
        filename = uuid.uuid4().hex + '.jpg'
        (settings.data_dir/'snapshots'/filename).write_bytes(jpeg)
        event = Event(camera_id=camera_id, kind='snapshot', label='Manual snapshot', snapshot=filename)
        db.add(event)
        enqueue_event(db,event,camera.name)
        audit(db, user, 'camera.snapshot', camera_id)
        db.commit()
        return event_dict(event, camera.name)

    @app.get('/api/cameras/{camera_id}/zones')
    def zones(camera_id: int, user=Depends(current_user), db=Depends(db_session)):
        get_camera(db, camera_id)
        return [{'id': z.id, 'name': z.name, 'points': z.points, 'classes': z.classes} for z in db.scalars(select(Zone).where(Zone.camera_id == camera_id))]

    @app.post('/api/cameras/{camera_id}/zones', status_code=201)
    def create_zone(camera_id: int, payload: ZoneInput, user=Depends(admin), db=Depends(db_session)):
        get_camera(db, camera_id)
        zone = Zone(camera_id=camera_id, **payload.model_dump())
        db.add(zone)
        audit(db, user, 'zone.created', camera_id)
        db.commit()
        return {'id': zone.id, **payload.model_dump()}

    @app.delete('/api/cameras/{camera_id}/zones/{zone_id}', status_code=204)
    def delete_zone(camera_id: int, zone_id: int, user=Depends(admin), db=Depends(db_session)):
        zone = db.get(Zone, zone_id)
        if not zone or zone.camera_id != camera_id:
            raise HTTPException(404, 'Zone not found')
        db.delete(zone)
        audit(db, user, 'zone.deleted', zone_id)
        db.commit()

    @app.get('/api/events')
    def events(camera_id: int | None = None, kind: str | None = None, acknowledged: bool | None = None,
               since: datetime | None = None, until: datetime | None = None,
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               user=Depends(current_user), db=Depends(db_session)):
        query = select(Event, Camera.name).join(Camera)
        if camera_id is not None:
            query = query.where(Event.camera_id == camera_id)
        if kind:
            query = query.where(Event.kind == kind)
        if acknowledged is not None:
            query = query.where(Event.acknowledged == acknowledged)
        if since:
            query = query.where(Event.created_at >= since)
        if until:
            query = query.where(Event.created_at <= until)
        count = db.scalar(select(func.count()).select_from(query.subquery()))
        return {'total': count, 'items': [event_dict(e,n) for e,n in db.execute(query.order_by(Event.id.desc()).limit(limit).offset(offset))]}

    @app.post('/api/events/{event_id}/acknowledge')
    def acknowledge(event_id: int, user=Depends(operator), db=Depends(db_session)):
        event = db.get(Event, event_id)
        if not event:
            raise HTTPException(404, 'Event not found')
        event.acknowledged, event.acknowledged_by = True, user.id
        audit(db, user, 'event.acknowledged', event_id)
        db.commit()
        return {'acknowledged': True}

    @app.get('/api/events/{event_id}/snapshot')
    def event_snapshot(event_id: int, user=Depends(current_user), db=Depends(db_session)):
        event = db.get(Event, event_id)
        if not event or not event.snapshot:
            raise HTTPException(404, 'Snapshot not found')
        path = settings.data_dir/'snapshots'/event.snapshot
        if not path.is_file():
            raise HTTPException(404, 'Snapshot expired')
        return FileResponse(path, media_type='image/jpeg')

    @app.get('/api/events/{event_id}')
    def event_detail(event_id:int,user=Depends(current_user),db=Depends(db_session)):
        row=db.execute(select(Event,Camera.name).join(Camera).where(Event.id==event_id)).first()
        if not row:
            raise HTTPException(404,'Event not found')
        return event_dict(*row)

    @app.get('/api/events/{event_id}/clip')
    def event_clip(event_id:int,user=Depends(current_user),db=Depends(db_session)):
        event=db.get(Event,event_id)
        if not event or event.clip_status!='ready' or not event.clip_filename:
            raise HTTPException(404,'Incident clip is not available')
        path=settings.data_dir/'clips'/event.clip_filename
        if not path.is_file():
            raise HTTPException(404,'Incident clip expired')
        return FileResponse(path,media_type='video/mp4')

    @app.get('/api/recordings')
    def recordings(camera_id: int | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   user=Depends(current_user), db=Depends(db_session)):
        query = select(Recording, Camera.name).join(Camera)
        if camera_id is not None:
            query = query.where(Recording.camera_id == camera_id)
        count = db.scalar(select(func.count()).select_from(query.subquery()))
        return {'total': count, 'items': [{'id': r.id, 'camera_name': n, 'camera_id': r.camera_id,
                'started_at': r.started_at, 'duration': r.duration, 'size_bytes': r.size_bytes,
                'playback_url':f'/api/recordings/{r.id}/play' if r.filename.endswith('.mp4') else None,
                'format':'mp4' if r.filename.endswith('.mp4') else 'avi',
                'download_url': f'/api/recordings/{r.id}/download'}
                for r,n in db.execute(query.order_by(Recording.id.desc()).limit(limit).offset(offset))]}

    @app.get('/api/recordings/{recording_id}/download')
    def recording_download(recording_id: int, user=Depends(current_user), db=Depends(db_session)):
        recording = db.get(Recording, recording_id)
        if not recording:
            raise HTTPException(404, 'Recording not found')
        path = settings.data_dir/'recordings'/recording.filename
        if not path.is_file():
            raise HTTPException(404, 'Recording expired')
        extension=path.suffix
        return FileResponse(path,media_type='video/mp4' if extension=='.mp4' else 'video/x-msvideo',
                            filename=f'mt-project-{recording_id}{extension}')

    @app.get('/api/recordings/{recording_id}/play')
    def recording_play(recording_id:int,user=Depends(current_user),db=Depends(db_session)):
        recording=db.get(Recording,recording_id)
        if not recording or not recording.filename.endswith('.mp4'):
            raise HTTPException(404,'MP4 recording not found')
        path=settings.data_dir/'recordings'/recording.filename
        if not path.is_file():
            raise HTTPException(404,'Recording expired')
        return FileResponse(path,media_type='video/mp4')

    @app.get('/api/system')
    def system(user=Depends(current_user), db=Depends(db_session)):
        disk = shutil.disk_usage(settings.data_dir)
        return {'product': 'MT Project', 'version': '0.2.0',
                'database': engine.dialect.name, 'model_available': bool(settings.model_path and Path(settings.model_path).is_file()),
                'device': settings.device, 'max_cameras': settings.max_cameras,
                'retention_days': settings.retention_days, 'media_quota_mb': settings.media_quota_mb,
                'clip_pre_seconds':settings.clip_pre_seconds,'clip_post_seconds':settings.clip_post_seconds,
                'disk_free_bytes': disk.free, 'upload_limit_mb': settings.upload_limit//1024//1024,
                'events': db.scalar(select(func.count()).select_from(Event)),
                'unacknowledged_intrusions': db.scalar(select(func.count()).select_from(Event).where(Event.kind == 'intrusion', Event.acknowledged.is_(False)))}

    @app.get('/api/audit')
    def audit_log(limit: int = Query(100, ge=1, le=200), user=Depends(admin), db=Depends(db_session)):
        return [{'id': a.id, 'user_id': a.user_id, 'action': a.action, 'target': a.target, 'created_at': a.created_at}
                for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(limit))]

    static = Path(__file__).resolve().parents[2]/'frontend'/'dist'
    if static.exists():
        app.mount('/', StaticFiles(directory=static, html=True), name='MT Project')
    return app
