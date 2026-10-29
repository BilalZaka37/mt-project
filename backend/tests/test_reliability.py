import time
from datetime import timedelta

import cv2
import numpy as np

from app.db import Camera, Event, utcnow
from conftest import TestDetector as DetectorFixture, wait_for
from test_api import upload


def configure_recording(client,camera_id,detect=True):
    assert client.put(f'/api/cameras/{camera_id}',json={'name':'Reliability validation','location':'Test',
        'detection_enabled':detect,'recording_enabled':True,'confidence':.45}).status_code==200


def test_slow_inference_does_not_slow_or_truncate_recording(logged_in,video):
    app,client=logged_in
    class SlowDetector(DetectorFixture):
        def detect(self,frame,confidence):
            time.sleep(.3)
            return super().detect(frame,confidence)
    app.state.manager.detector_factory=SlowDetector
    camera_id=upload(client,video)
    configure_recording(client,camera_id)
    started=time.monotonic()
    client.post(f'/api/cameras/{camera_id}/start')
    wait_for(lambda:app.state.manager.state(camera_id)['capture_frames']>=10)
    state=app.state.manager.state(camera_id)
    assert state['recording_frames']>state['inference_frames']
    wait_for(lambda:app.state.manager.state(camera_id)['status']=='completed')
    state=app.state.manager.state(camera_id)
    assert state['capture_frames']==24
    assert state['inference_frames']<state['capture_frames']
    assert state['inference_skipped']>0
    assert state['recording_dropped']==0 and state['recording_status']=='finalized'
    assert state['recording_frames']==24
    assert time.monotonic()-started<6
    recording=client.get('/api/recordings').json()['items'][0]
    assert abs(recording['duration']-2.4)<.1


def test_inference_failure_keeps_recording_alive(logged_in,video):
    app,client=logged_in
    class BrokenDetector:
        def __init__(self,*_): pass
        def detect(self,*_): raise RuntimeError('Intentional test inference failure')
    app.state.manager.detector_factory=BrokenDetector
    camera_id=upload(client,video)
    configure_recording(client,camera_id)
    client.post(f'/api/cameras/{camera_id}/start')
    wait_for(lambda:app.state.manager.state(camera_id)['status']=='completed')
    state=app.state.manager.state(camera_id)
    assert state['detector']=='failed'
    assert state['capture_frames']==24 and state['recording_frames']==24
    assert client.get('/api/recordings').json()['total']==1


def test_incident_has_pre_and_post_frames_and_playable_protected_mp4(logged_in,video):
    app,client=logged_in
    app.state.settings.clip_pre_seconds=.4
    app.state.settings.clip_post_seconds=.5
    camera_id=upload(client,video)
    client.post(f'/api/cameras/{camera_id}/start')
    wait_for(lambda:app.state.manager.state(camera_id)['capture_frames']>=9)
    client.post(f'/api/cameras/{camera_id}/zones',json={'name':'New boundary',
        'points':[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],'classes':['person']})
    wait_for(lambda:client.get('/api/events?kind=intrusion').json()['total']==1)
    event_id=client.get('/api/events?kind=intrusion').json()['items'][0]['id']
    def ready():
        event=client.get(f'/api/events/{event_id}').json()
        return event if event['clip_status']=='ready' else None
    evidence=wait_for(ready)
    assert .3<=evidence['clip_offset']<=.65
    assert .8<=evidence['clip_duration']<=1.3
    assert evidence['clip_truncated'] is False
    assert evidence['details']['rule']=='ground-point-entry/v1'
    response=client.get(evidence['clip_url'],headers={'Range':'bytes=0-127'})
    assert response.status_code==206 and len(response.content)==128
    assert response.headers['content-type']=='video/mp4'
    with app.state.sessions() as db:
        event=db.get(Event,event_id)
        cap=cv2.VideoCapture(str(app.state.settings.data_dir/'clips'/event.clip_filename))
        assert cap.read()[0]
        assert cap.get(cv2.CAP_PROP_FPS)==10
        cap.release()


def test_stream_reconnects_and_records_health_transitions(logged_in):
    app,client=logged_in
    class Capture:
        def __init__(self,index): self.index,self.frames=index,0
        def isOpened(self): return self.index>0
        def get(self,_): return 10
        def release(self): pass
        def read(self):
            time.sleep(.04)
            self.frames+=1
            if self.index==1 and self.frames>3:return False,None
            return True,np.zeros((120,160,3),np.uint8)
    calls=[]
    def factory(*_):
        result=Capture(len(calls));calls.append(result);return result
    app.state.manager.capture_factory=factory
    camera_id=client.post('/api/cameras',json={'name':'Network recovery test','source':'http://127.0.0.1/test',
        'detection_enabled':False,'recording_enabled':True}).json()['id']
    client.post(f'/api/cameras/{camera_id}/start')
    wait_for(lambda:app.state.manager.state(camera_id)['reconnects']>=2,timeout=8)
    assert client.get('/api/events?kind=offline').json()['total']==2
    assert client.get('/api/events?kind=recovered').json()['total']==2
    client.post(f'/api/cameras/{camera_id}/stop')
    wait_for(lambda:app.state.manager.state(camera_id)['status']=='stopped')
    assert client.get('/api/recordings').json()['total']>=1


def test_restart_marks_incomplete_clip_explicitly_failed(logged_in):
    app,client=logged_in
    camera_id=client.post('/api/cameras',json={'name':'Interrupted','source':'rtsp://127.0.0.1/test'}).json()['id']
    with app.state.sessions() as db:
        event=Event(camera_id=camera_id,kind='intrusion',label='person',clip_status='collecting')
        db.add(event);db.commit();event_id=event.id
    from app.media import IncidentEncoder
    encoder=IncidentEncoder(app.state.settings,app.state.sessions)
    encoder.start();encoder.close()
    evidence=client.get(f'/api/events/{event_id}').json()
    assert evidence['clip_status']=='failed' and 'restart' in evidence['clip_error']
