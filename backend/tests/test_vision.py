"""Opt-in test with real model inference and real video, never a stub detector.

MT_TEST_MODEL=<weights.pt> MT_TEST_VIDEO=<video.avi> python -m pytest tests/test_vision.py -v
"""
import os
from pathlib import Path

import cv2
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import User
from app.main import create_app
from app.security import passwords
from conftest import wait_for


@pytest.mark.skipif(not os.getenv('MT_TEST_MODEL') or not os.getenv('MT_TEST_VIDEO'), reason='Requires real YOLO weights and a pedestrian video')
def test_real_yolo_tracking_intrusion_and_recording(application, tmp_path):
    old_app, _ = application
    settings = old_app.state.settings
    settings.model_path = str(Path(os.environ['MT_TEST_MODEL']).resolve())
    source = cv2.VideoCapture(os.environ['MT_TEST_VIDEO'])
    ok, frame = source.read()
    assert ok
    height,width=frame.shape[:2]
    short=tmp_path/'real-people.avi'
    writer=cv2.VideoWriter(str(short), cv2.VideoWriter_fourcc(*'MJPG'),10,(width,height))
    assert writer.isOpened()
    for _ in range(35):
        if not ok:
            break
        writer.write(frame)
        ok,frame=source.read()
    writer.release();source.release()
    app=create_app(settings)
    with TestClient(app,headers={'X-MT-Request':'1'}) as client:
        assert client.post('/api/auth/login',json={'email':'admin@example.test','password':'test-password-1234'}).status_code==200
        with short.open('rb') as video:
            response=client.post('/api/cameras/upload',data={'name':'Real pedestrian footage'},files={'file':('people.avi',video,'video/x-msvideo')})
        assert response.status_code==201,response.text
        camera_id=response.json()['id']
        assert client.put(f'/api/cameras/{camera_id}',json={'name':'Real pedestrian footage','location':'OpenCV sample','confidence':.25,'detection_enabled':True,'recording_enabled':True}).status_code==200
        assert client.post(f'/api/cameras/{camera_id}/zones',json={'name':'Pedestrian test zone','points':[[0,0],[1,0],[1,1],[0,1]],'classes':['person']}).status_code==201
        assert client.post(f'/api/cameras/{camera_id}/start').status_code==200
        wait_for(lambda:app.state.manager.state(camera_id)['status']=='completed',timeout=180)
        state=app.state.manager.state(camera_id)
        assert state['detector']=='ready',state
        result=client.get('/api/events?kind=intrusion').json()
        assert result['total']>0,result
        assert all(e['label']=='person' and e['track_id'] is not None for e in result['items'])
        snapshot=client.get(result['items'][0]['snapshot_url'])
        assert snapshot.status_code==200 and snapshot.content.startswith(b'\xff\xd8')
        recordings=client.get('/api/recordings').json()['items']
        assert len(recordings)==1 and recordings[0]['duration']>=3
        assert client.get(recordings[0]['download_url']).content[4:8]==b'ftyp'
        wait_for(lambda:client.get(f"/api/events/{result['items'][0]['id']}").json()['clip_status']=='ready',timeout=60)
        clip=client.get(f"/api/events/{result['items'][0]['id']}").json()
        downloaded=client.get(clip['clip_url'])
        decoded=tmp_path/'incident.mp4'
        decoded.write_bytes(downloaded.content)
        cap=cv2.VideoCapture(str(decoded))
        assert cap.read()[0], 'Real incident MP4 must decode'
        cap.release()
        print(f"REAL VISION RESULT: {result['total']} person zone-entry events; {len(recordings)} recording; model=YOLO11n; device=cpu")
