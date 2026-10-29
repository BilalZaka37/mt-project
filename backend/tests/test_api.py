import time
from datetime import timedelta

import cv2
import pytest
from sqlalchemy import select

from app.db import Camera, Event, Recording, Session, User, Zone, utcnow
from app.security import token_hash
from conftest import wait_for


def login(client, role='admin'):
    return client.post('/api/auth/login', json={'email':f'{role}@example.test','password':'test-password-1234'})


def upload(client, video):
    with video.open('rb') as data:
        response = client.post('/api/cameras/upload', data={'name':'Test video'}, files={'file':('video.avi',data,'video/x-msvideo')})
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_auth_cookie_csrf_session_revocation(application):
    app, client = application
    assert client.get('/api/cameras').status_code == 401
    assert login(client).status_code == 200
    cookie = client.cookies.get('mt_session')
    assert cookie
    assert client.get('/api/auth/me').json()['role'] == 'admin'
    assert client.post('/api/auth/logout', headers={'X-MT-Request':''}).status_code == 403
    assert client.post('/api/auth/logout', headers={'Origin':'https://untrusted.test'}).status_code == 403
    assert client.post('/api/auth/logout').status_code == 204
    client.cookies.set('mt_session', cookie)
    assert client.get('/api/auth/me').status_code == 401
    with app.state.sessions() as db:
        assert db.get(Session, token_hash(cookie)) is None


@pytest.mark.parametrize('role', ['operator','viewer'])
def test_role_boundaries(application, role):
    _, client = application
    login(client, role)
    assert client.get('/api/cameras').status_code == 200
    assert client.get('/api/users').status_code == 403
    assert client.post('/api/cameras', json={'name':'denied','source':'rtsp://localhost/a'}).status_code == 403
    assert client.get('/api/audit').status_code == 403


def test_encrypted_source_and_crud(logged_in):
    app, client = logged_in
    source = 'rtsp://sensitive:secret@192.168.1.10:554/stream'
    response = client.post('/api/cameras', json={'name':'Entrance','location':'North','source':source})
    assert response.status_code == 201
    camera_id = response.json()['id']
    assert 'secret' not in response.text and 'source_encrypted' not in response.text
    with app.state.sessions() as db:
        camera = db.get(Camera, camera_id)
        assert source not in camera.source_encrypted
        assert app.state.cipher.decrypt(camera.source_encrypted.encode()).decode() == source
    assert client.put(f'/api/cameras/{camera_id}',json={'name':'Changed','location':'South','detection_enabled':False,'recording_enabled':False,'confidence':.6}).status_code == 200
    assert client.post('/api/cameras', json={'name':'Unsafe','source':'file:///etc/passwd'}).status_code == 422
    assert client.delete(f'/api/cameras/{camera_id}').status_code == 204
    assert not client.get('/api/cameras').json()


def test_upload_pipeline_intrusion_recording_and_evidence(logged_in, video):
    app, client = logged_in
    camera_id = upload(client,video)
    response = client.put(f'/api/cameras/{camera_id}',json={'name':'Test video','location':'Test','detection_enabled':True,'recording_enabled':True,'confidence':.45})
    assert response.status_code == 200
    zone = client.post(f'/api/cameras/{camera_id}/zones', json={'name':'Restricted','points':[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],'classes':['person']})
    assert zone.status_code == 201
    assert client.post(f'/api/cameras/{camera_id}/start').status_code == 200
    wait_for(lambda: app.state.manager.jpeg(camera_id))
    assert client.get(f'/api/cameras/{camera_id}/frame').headers['content-type'] == 'image/jpeg'
    snap = client.post(f'/api/cameras/{camera_id}/snapshot')
    assert snap.status_code == 201
    wait_for(lambda: app.state.manager.state(camera_id)['status']=='completed')
    events = client.get('/api/events?kind=intrusion').json()
    assert events['total'] == 1, events
    event = events['items'][0]
    assert event['zone_name'] == 'Restricted' and event['track_id'] == 7
    assert client.get(event['snapshot_url']).content.startswith(b'\xff\xd8')
    assert client.post(f"/api/events/{event['id']}/acknowledge").status_code == 200
    assert client.get('/api/events?kind=intrusion&acknowledged=true').json()['total'] == 1
    assert client.get(f'/api/events?camera_id={camera_id+100}').json()['total'] == 0
    recordings = client.get('/api/recordings').json()['items']
    assert len(recordings)==1
    recording = recordings[0]
    assert recording['duration']>0 and recording['size_bytes']>0
    downloaded=client.get(recording['download_url'])
    assert downloaded.content[4:8]==b'ftyp'
    assert recording['format']=='mp4'
    assert client.get(recording['playback_url'],headers={'Range':'bytes=0-127'}).status_code==206
    wait_for(lambda:client.get(f"/api/events/{event['id']}").json()['clip_status']=='ready')
    evidence=client.get(f"/api/events/{event['id']}").json()
    assert evidence['clip_truncated'] is True
    assert evidence['clip_duration']>0
    assert client.get(evidence['clip_url']).content[4:8]==b'ftyp'
    assert client.get(f'/api/cameras/{camera_id}/frame').status_code==503
    client.cookies.clear()
    assert client.get(recording['download_url']).status_code == 401
    assert client.get(event['snapshot_url']).status_code == 401
    assert client.get(evidence['clip_url']).status_code == 401
    login(client)
    assert client.delete(f'/api/cameras/{camera_id}').status_code == 204
    assert client.get('/api/events').json()['total']==0
    assert not list((app.state.settings.data_dir/'uploads').iterdir())
    assert not list((app.state.settings.data_dir/'snapshots').iterdir())
    assert not list((app.state.settings.data_dir/'recordings').iterdir())
    assert not list((app.state.settings.data_dir/'clips').iterdir())


def test_upload_limits_invalid_video_and_paths(logged_in):
    app, client = logged_in
    assert client.post('/api/cameras/upload',data={'name':'Invalid'},files={'file':('bad.mp4',b'not video')}).status_code==400
    assert client.post('/api/cameras/upload',data={'name':'Invalid'},files={'file':('payload.txt',b'bad')}).status_code==400
    app.state.settings.upload_limit=20
    assert client.post('/api/cameras/upload',data={'name':'Large'},files={'file':('../../large.avi',b'a'*30)}).status_code==413
    assert not list((app.state.settings.data_dir/'uploads').iterdir())


def test_missing_yolo_keeps_real_video_available(logged_in,video):
    from app.detector import YOLODetector
    app, client = logged_in
    app.state.manager.detector_factory=YOLODetector
    camera_id=upload(client,video)
    client.post(f'/api/cameras/{camera_id}/start')
    wait_for(lambda:app.state.manager.state(camera_id)['status']=='online')
    state=client.get('/api/cameras').json()[0]
    assert state['detector']=='unavailable' and state['objects']==0
    assert 'Detection unavailable' in state['error']
    assert client.get(f'/api/cameras/{camera_id}/frame').status_code==200
    assert client.get('/api/events').json()['total']==0


def test_viewer_cannot_control_or_acknowledge(logged_in,video):
    app, client=logged_in
    camera_id=upload(client,video)
    login(client,'viewer')
    for path in [f'/cameras/{camera_id}/start',f'/cameras/{camera_id}/stop',f'/cameras/{camera_id}/snapshot','/events/1/acknowledge']:
        assert client.post('/api'+path).status_code==403


def test_password_change_revokes_all_sessions(logged_in):
    app, client=logged_in
    old_cookie=client.cookies.get('mt_session')
    assert client.post('/api/auth/password',json={'current_password':'wrong','new_password':'replacement-123456'}).status_code==400
    assert client.post('/api/auth/password',json={'current_password':'test-password-1234','new_password':'replacement-123456'}).status_code==204
    client.cookies.set('mt_session',old_cookie)
    assert client.get('/api/auth/me').status_code==401
    assert login(client).status_code==401
    assert client.post('/api/auth/login',json={'email':'admin@example.test','password':'replacement-123456'}).status_code==200


def test_access_revoked_immediately_and_duplicate_users(logged_in):
    app,client=logged_in
    assert client.post('/api/users',json={'email':'viewer@example.test','password':'test-password-1234','role':'viewer'}).status_code==409
    with app.state.sessions() as db:
        viewer=db.scalar(select(User).where(User.role=='viewer'))
        viewer_id=viewer.id
    login(client,'viewer')
    cookie=client.cookies.get('mt_session')
    login(client,'admin')
    assert client.post(f'/api/users/{viewer_id}/deactivate').status_code==204
    client.cookies.clear()
    client.cookies.set('mt_session',cookie)
    assert client.get('/api/auth/me').status_code==401


def test_session_expiry_and_login_rate_limit(application):
    app,client=application
    login(client)
    with app.state.sessions() as db:
        session=db.get(Session,token_hash(client.cookies.get('mt_session')))
        session.expires_at=utcnow()-timedelta(seconds=1)
        db.commit()
    assert client.get('/api/auth/me').status_code==401
    for i in range(9):
        assert client.post('/api/auth/login',json={'email':'nobody@example.test','password':'wrong'}).status_code==401
    assert login(client).status_code==429


def test_retention_and_quota_remove_finalized_evidence(logged_in):
    app,client=logged_in
    camera_id=client.post('/api/cameras',json={'name':'Retention','source':'rtsp://localhost/test'}).json()['id']
    settings=app.state.settings
    (settings.data_dir/'snapshots'/'old.jpg').write_bytes(b'old')
    (settings.data_dir/'recordings'/'old.avi').write_bytes(b'old')
    with app.state.sessions() as db:
        db.add(Event(camera_id=camera_id,kind='snapshot',label='old',snapshot='old.jpg',created_at=utcnow()-timedelta(days=9)))
        db.add(Recording(camera_id=camera_id,filename='old.avi',started_at=utcnow()-timedelta(days=9),duration=1,size_bytes=3))
        db.commit()
    app.state.manager.prune()
    assert client.get('/api/events').json()['total']==0
    assert client.get('/api/recordings').json()['total']==0
    (settings.data_dir/'snapshots'/'new.jpg').write_bytes(b'new')
    with app.state.sessions() as db:
        db.add(Event(camera_id=camera_id,kind='snapshot',label='new',snapshot='new.jpg'))
        db.commit()
    settings.media_quota_mb=0
    app.state.manager.prune()
    assert client.get('/api/events').json()['items'][0]['snapshot_url'] is None
    assert not (settings.data_dir/'snapshots'/'new.jpg').exists()


def test_recording_preserves_file_timing_at_30_fps(logged_in,tmp_path):
    import numpy as np
    app,client=logged_in
    source=tmp_path/'thirty-fps.avi'
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'MJPG'),30,(160,120))
    assert writer.isOpened()
    for _ in range(60):
        writer.write(np.zeros((120,160,3),dtype=np.uint8))
    writer.release()
    camera_id=upload(client,source)
    assert client.put(f'/api/cameras/{camera_id}',json={'name':'Timing','location':'Test','detection_enabled':False,'recording_enabled':True,'confidence':.45}).status_code==200
    client.post(f'/api/cameras/{camera_id}/start')
    wait_for(lambda:app.state.manager.state(camera_id)['status']=='completed')
    recording=client.get('/api/recordings').json()['items'][0]
    assert abs(recording['duration']-2)<.15
    path=app.state.settings.data_dir/'recordings'
    cap=cv2.VideoCapture(str(next(path.glob('*.mp4'))))
    assert cap.get(cv2.CAP_PROP_FPS)==10
    assert 19<=cap.get(cv2.CAP_PROP_FRAME_COUNT)<=21
    cap.release()
    assert client.get('/api/cameras').json()[0]['enabled'] is False


def test_two_camera_workers_are_isolated_and_capacity_is_enforced(logged_in,video):
    app,client=logged_in
    first,second=upload(client,video),upload(client,video)
    app.state.settings.max_cameras=1
    assert client.post(f'/api/cameras/{first}/start').status_code==200
    assert client.post(f'/api/cameras/{second}/start').status_code==409
    app.state.settings.max_cameras=2
    assert client.post(f'/api/cameras/{second}/start').status_code==200
    wait_for(lambda:all(app.state.manager.state(i)['status']=='completed' for i in (first,second)))
    for camera_id in (first,second):
        result=client.get(f'/api/events?camera_id={camera_id}').json()
        assert result['total']==1
        assert result['items'][0]['track_id']==7
    assert app.state.manager.runtimes[first] is not app.state.manager.runtimes[second]


def test_api_documentation_is_self_hosted_with_csrf_header(application):
    _,client=application
    response=client.get('/docs')
    assert response.status_code==200
    assert 'MT Project API' in response.text
    assert 'cdn.jsdelivr' not in response.text
    assert "request.headers['X-MT-Request'] = '1'" in response.text
    assert 'nonce-' in response.headers['content-security-policy']
    assert client.get('/docs-assets/swagger-ui-bundle.js').status_code==200
    assert client.get('/docs-assets/swagger-ui.css').status_code==200
    assert client.get('/openapi.json').json()['info']['title']=='MT Project'
