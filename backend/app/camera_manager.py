import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta

import cv2
import numpy as np
from sqlalchemy import select

from .alerts import enqueue_event
from .db import AlertDelivery, Camera, Event, Recording, Zone, utcnow
from .detector import YOLODetector
from .media import FramePacket, IncidentEncoder, SegmentRecorder, decode
from .rules import AlertRules

log = logging.getLogger('mt-project.cameras')


@dataclass
class Runtime:
    stop: threading.Event = field(default_factory=threading.Event)
    capture_done: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=threading.Condition)
    lock: threading.RLock = field(default_factory=threading.RLock)
    thread: threading.Thread | None = None
    inference_thread: threading.Thread | None = None
    status: str = 'connecting'
    detector: str = 'loading'
    error: str | None = None
    detector_error: str | None = None
    recording_error: str | None = None
    fps: float = 0
    objects: int = 0
    latest: FramePacket | None = None
    annotated: bytes | None = None
    annotated_at: float = 0
    history: deque = field(default_factory=lambda: deque(maxlen=60))
    pending_clips: list = field(default_factory=list)
    capture_frames: int = 0
    inference_frames: int = 0
    inference_skipped: int = 0
    recording_frames: int = 0
    recording_dropped: int = 0
    recording_status: str = 'disabled'
    reconnects: int = 0
    generation: int = 0
    last_seen: str | None = None


def open_capture(source, kind):
    return cv2.VideoCapture(source, cv2.CAP_FFMPEG,
        [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])


class CameraManager:
    def __init__(self, settings, session_factory, cipher, detector_factory=YOLODetector, capture_factory=open_capture):
        self.settings, self.db, self.cipher = settings, session_factory, cipher
        self.detector_factory, self.capture_factory = detector_factory, capture_factory
        self.runtimes, self.lock = {}, threading.RLock()
        self.shutdown, self.janitor = threading.Event(), None
        self.clips = IncidentEncoder(settings, session_factory)

    def resume(self):
        self.clips.start()
        with self.db() as db:
            for camera in db.scalars(select(Camera).where(Camera.enabled.is_(True))):
                try:
                    self.start(camera.id)
                except RuntimeError:
                    log.exception('Camera %s could not resume within capacity', camera.id)
        self.janitor = threading.Thread(target=self._maintenance, name='mt-retention', daemon=True)
        self.janitor.start()

    def start(self, camera_id):
        with self.lock:
            old = self.runtimes.get(camera_id)
            if old and old.thread.is_alive():
                if old.stop.is_set():
                    raise RuntimeError('Camera is still stopping. Retry in a few seconds.')
                return
            if sum(r.thread.is_alive() for r in self.runtimes.values()) >= self.settings.max_cameras:
                raise RuntimeError('Camera worker capacity reached')
            runtime = Runtime()
            runtime.thread = threading.Thread(target=self._run, args=(camera_id, runtime), name=f'mt-capture-{camera_id}', daemon=True)
            self.runtimes[camera_id] = runtime
            runtime.thread.start()

    def stop(self, camera_id):
        with self.lock:
            runtime = self.runtimes.get(camera_id)
        if runtime:
            runtime.stop.set()
            runtime.status = 'stopping'
            with runtime.condition:
                runtime.condition.notify_all()
            runtime.thread.join(timeout=.2)

    def close(self):
        self.shutdown.set()
        for runtime in list(self.runtimes.values()):
            runtime.stop.set()
            with runtime.condition:
                runtime.condition.notify_all()
        for runtime in list(self.runtimes.values()):
            runtime.thread.join(timeout=45)
        self.clips.close()
        if self.janitor:
            self.janitor.join(timeout=2)

    def state(self, camera_id):
        with self.lock:
            r = self.runtimes.get(camera_id)
        if not r:
            r = Runtime(status='stopped', detector='not started')
        with r.lock:
            age = round(time.monotonic()-r.latest.received_at, 1) if r.latest else None
            inference_age = round(time.monotonic()-r.annotated_at, 1) if r.annotated_at else None
            recording_ok = r.recording_status in ('disabled','recording','finalized','waiting') and r.recording_dropped==0
            readiness = 'ready' if r.status=='online' and age is not None and age<3 and r.detector in ('ready','disabled') and recording_ok else 'attention' if r.status in ('online','offline','reconnecting','error') else 'inactive'
            return {'status':r.status, 'detector':r.detector, 'error':r.error or r.detector_error or r.recording_error,
                'fps':round(r.fps,1), 'objects':r.objects if inference_age is not None and inference_age<3 else 0,
                'frame_age':age, 'inference_age':inference_age, 'readiness':readiness,
                'capture_frames':r.capture_frames, 'inference_frames':r.inference_frames,
                'inference_skipped':r.inference_skipped, 'recording_frames':r.recording_frames,
                'recording_dropped':r.recording_dropped, 'recording_status':r.recording_status,
                'reconnects':r.reconnects, 'last_seen':r.last_seen}

    def jpeg(self, camera_id):
        with self.lock:
            r = self.runtimes.get(camera_id)
        if not r:
            return None
        with r.lock:
            if not r.latest or time.monotonic()-r.latest.received_at>10 or r.status!='online':
                return None
            return r.annotated if r.annotated and time.monotonic()-r.annotated_at<2 else r.latest.jpeg

    def _health_event(self, camera, kind):
        with self.db() as db:
            event = Event(camera_id=camera.id, kind=kind,
                label='Camera connection lost' if kind=='offline' else 'Camera connection recovered',
                details={'reason':'Video source unavailable' if kind=='offline' else 'Fresh frames received after reconnection'})
            db.add(event)
            enqueue_event(db, event, camera.name)
            db.commit()

    def _run(self, camera_id, r):
        cap, recorder, camera, completed = None, None, None, False
        origin, failures, outage, source_frames = time.monotonic(), 0, False, 0
        try:
            with self.db() as db:
                camera = db.get(Camera, camera_id)
                if not camera:
                    return
                source = self.cipher.decrypt(camera.source_encrypted.encode()).decode()
            if camera.recording_enabled:
                recorder = SegmentRecorder(camera_id, self.settings, self.db, r)
            if camera.detection_enabled:
                r.inference_thread = threading.Thread(target=self._infer, args=(camera,r), name=f'mt-infer-{camera_id}', daemon=True)
                r.inference_thread.start()
            else:
                r.detector = 'disabled'
            last_sample = -1e9
            while not r.stop.is_set():
                if cap is None:
                    r.status = 'reconnecting' if outage else 'connecting'
                    cap = self.capture_factory(source, camera.kind)
                    if cap.isOpened():
                        source_fps = cap.get(cv2.CAP_PROP_FPS)
                        source_fps = source_fps if 0<source_fps<240 else 15
                        source_frames = 0
                        r.generation += 1
                    else:
                        cap.release()
                        cap = None
                tick = time.monotonic()
                ok, frame = cap.read() if cap is not None else (False,None)
                if not ok:
                    if cap is not None:
                        cap.release()
                        cap = None
                    if camera.kind=='file':
                        if source_frames == 0:
                            raise RuntimeError('Uploaded source could not be read')
                        completed = True
                        break
                    if not outage:
                        r.generation += 1
                        self._health_event(camera,'offline')
                        outage = True
                        self._flush_clips(r, final=True)
                        with r.lock:
                            r.history.clear()
                            r.latest, r.annotated = None, None
                        if recorder:
                            recorder.discontinuity()
                    r.status = 'offline'
                    r.error = 'Video source unavailable. Automatic reconnection is active.'
                    failures += 1
                    r.stop.wait(min(30, 2**min(failures-1,5)))
                    continue
                if outage:
                    r.reconnects += 1
                    self._health_event(camera,'recovered')
                    outage = False
                failures, r.error = 0, None
                if frame.shape[1]>1280:
                    frame = cv2.resize(frame,(1280,int(frame.shape[0]*1280/frame.shape[1])))
                frame = frame[:frame.shape[0]//2*2,:frame.shape[1]//2*2]
                media_clock = source_frames/source_fps if camera.kind=='file' else time.monotonic()-origin
                source_frames += 1
                ok, jpeg = cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,85])
                if not ok:
                    continue
                r.capture_frames += 1
                packet = FramePacket(r.capture_frames, media_clock, utcnow(), time.monotonic(), jpeg.tobytes(), r.generation)
                with r.lock:
                    r.latest, r.status = packet, 'online'
                    r.last_seen = packet.captured_at.isoformat()
                    if packet.clock-last_sample>=.19:
                        r.history.append(packet)
                        last_sample = packet.clock
                        while r.history and r.history[0].clock<packet.clock-self.settings.clip_pre_seconds-1:
                            r.history.popleft()
                        for job in r.pending_clips:
                            if packet.clock<=job['end']+.2:
                                job['packets'].append(packet)
                if recorder:
                    recorder.push(packet)
                self._flush_clips(r)
                with r.condition:
                    r.condition.notify_all()
                interval = 1/source_fps if camera.kind=='file' else 0
                elapsed = max(time.monotonic()-tick, interval, .001)
                r.fps = 1/elapsed
                r.stop.wait(max(0,interval-(time.monotonic()-tick)))
            r.status = 'finalizing'
        except Exception:
            log.exception('Capture failed for camera %s', camera_id)
            r.status, r.error = 'error','Video capture failed. Check source, disk, and server logs.'
        finally:
            if cap is not None:
                cap.release()
            r.capture_done.set()
            with r.condition:
                r.condition.notify_all()
            if r.inference_thread:
                r.inference_thread.join()
            self._flush_clips(r,final=True)
            if recorder:
                recorder.finish()
            if camera and camera.kind=='file':
                with self.db() as db:
                    persisted = db.get(Camera,camera_id)
                    if persisted:
                        persisted.enabled = False
                        db.commit()
            with r.lock:
                r.latest, r.annotated, r.objects, r.fps = None, None, 0, 0
                if r.stop.is_set():
                    r.status = 'stopped'
                elif completed:
                    r.status = 'completed'

    def _infer(self, camera, r):
        try:
            detector = self.detector_factory(self.settings.model_path,self.settings.device)
            r.detector = 'ready'
        except Exception:
            log.exception('Detector unavailable for camera %s',camera.id)
            r.detector, r.detector_error = 'unavailable','Detection unavailable. Check model file, vision dependencies, and device.'
            return
        sequence, generation, rules = 0, 0, AlertRules()
        while not r.stop.is_set():
            with r.condition:
                r.condition.wait_for(lambda:r.stop.is_set() or r.capture_done.is_set() or (r.latest and r.latest.seq!=sequence),timeout=.5)
            if r.stop.is_set():
                break
            with r.lock:
                packet = r.latest
            if packet is None or packet.seq==sequence:
                if r.capture_done.is_set():
                    break
                continue
            r.inference_skipped += max(0,packet.seq-sequence-1)
            sequence = packet.seq
            if packet.generation!=generation:
                rules = AlertRules()
                if generation and hasattr(detector,'reset'):
                    detector.reset()
                generation = packet.generation
            try:
                frame = decode(packet)
                objects = detector.detect(frame,camera.confidence)
                r.inference_frames += 1
                if packet.generation!=r.generation:
                    continue
                with self.db() as db:
                    zones = list(db.scalars(select(Zone).where(Zone.camera_id==camera.id)))
                height,width = frame.shape[:2]
                for zone in zones:
                    contour = np.asarray([(int(x*width),int(y*height)) for x,y in zone.points],np.int32)
                    cv2.polylines(frame,[contour],True,(40,185,255),2)
                    cv2.putText(frame,zone.name,tuple(contour[0]),cv2.FONT_HERSHEY_SIMPLEX,.5,(40,185,255),1)
                for obj in objects:
                    x1,y1,x2,y2 = map(int,obj['box'])
                    cv2.rectangle(frame,(x1,y1),(x2,y2),(172,218,50),2)
                    cv2.putText(frame,f"{obj['label']} #{obj['track_id']} {obj['confidence']:.0%}",
                        (x1,max(18,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,.5,(172,218,50),1)
                ok,jpeg = cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,85])
                if not ok:
                    continue
                encoded = jpeg.tobytes()
                with r.lock:
                    r.annotated,r.annotated_at,r.objects = encoded,packet.received_at,len(objects)
                for kind,obj,zone_name in rules.evaluate(objects,zones,width,height,packet.clock):
                    self._detection_event(camera,r,packet,encoded,kind,obj,zone_name,width,height)
            except Exception:
                log.exception('Inference failed for camera %s',camera.id)
                r.detector,r.detector_error = 'failed','Inference failed. Recording continues independently; check server logs.'
                break

    def _detection_event(self,camera,r,packet,jpeg,kind,obj,zone_name,width,height):
        filename = uuid.uuid4().hex+'.jpg'
        (self.settings.data_dir/'snapshots'/filename).write_bytes(jpeg)
        with self.db() as db:
            event = Event(camera_id=camera.id,kind=kind,label=obj['label'],confidence=obj['confidence'],
                track_id=obj['track_id'],zone_name=zone_name,snapshot=filename,created_at=packet.captured_at,
                clip_status='collecting' if kind=='intrusion' else 'none',
                details={'reason':f"Tracked {obj['label']} entered {zone_name}" if kind=='intrusion' else f"Tracked {obj['label']} detected",
                         'rule':'ground-point-entry/v1' if kind=='intrusion' else 'tracked-object/v1',
                         'source_seconds':round(packet.clock,3),'frame_sequence':packet.seq,
                         'box':obj['box'],'frame_size':[width,height],
                         'confidence_threshold':camera.confidence,'recorded_source':camera.kind=='file'})
            db.add(event)
            enqueue_event(db,event,camera.name)
            db.commit()
            event_id = event.id
        if kind=='intrusion':
            with r.lock:
                if packet.generation!=r.generation or len(r.pending_clips)>=16:
                    saturated = True
                else:
                    saturated = False
                    packets = [p for p in r.history if packet.clock-self.settings.clip_pre_seconds<=p.clock<=packet.clock+self.settings.clip_post_seconds and p.generation==packet.generation]
                    packets.append(packet)
                    r.pending_clips.append({'id':event_id,'trigger':packet.clock,
                        'end':packet.clock+self.settings.clip_post_seconds,'packets':packets})
            if saturated:
                self.clips.fail(event_id,'Incident buffer capacity reached; snapshot evidence is retained.')

    def _flush_clips(self,r,final=False):
        ready = []
        with r.lock:
            clock = r.latest.clock if r.latest else -1
            pending = []
            for job in r.pending_clips:
                if final or clock>=job['end']:
                    ready.append(job)
                else:
                    pending.append(job)
            r.pending_clips = pending
        for job in ready:
            packets = job['packets']
            clocks = [p.clock for p in packets]
            truncated = not clocks or min(clocks)>job['trigger']-self.settings.clip_pre_seconds+.25 or max(clocks)<job['end']-.25
            self.clips.submit(job['id'],packets,job['trigger'],truncated)

    def _maintenance(self):
        while not self.shutdown.wait(60):
            try:
                self.prune()
            except Exception:
                log.exception('Retention cleanup failed')

    def prune(self):
        cutoff = utcnow()-timedelta(days=self.settings.retention_days)
        with self.db() as db:
            for event in db.scalars(select(Event).where(Event.created_at<cutoff)):
                for folder,name in [('snapshots',event.snapshot),('clips',event.clip_filename)]:
                    if name:
                        (self.settings.data_dir/folder/name).unlink(missing_ok=True)
                db.delete(event)
            for clip in db.scalars(select(Recording).where(Recording.started_at<cutoff)):
                (self.settings.data_dir/'recordings'/clip.filename).unlink(missing_ok=True)
                db.delete(clip)
            for delivery in db.scalars(select(AlertDelivery).where(AlertDelivery.created_at<cutoff,AlertDelivery.status.in_(['delivered','dead']))):
                db.delete(delivery)
            db.commit()
            entries = [(c.started_at,'recordings',c.filename,c) for c in db.scalars(select(Recording))]
            for event in db.scalars(select(Event)):
                if event.snapshot:
                    entries.append((event.created_at,'snapshots',event.snapshot,event))
                if event.clip_filename:
                    entries.append((event.created_at,'clips',event.clip_filename,event))
            entries.sort(key=lambda item:item[0])
            total = sum((self.settings.data_dir/f/n).stat().st_size for _,f,n,_ in entries if (self.settings.data_dir/f/n).exists())
            for _,folder,name,row in entries:
                if total<=self.settings.media_quota_mb*1024*1024:
                    break
                path = self.settings.data_dir/folder/name
                if path.exists():
                    total -= path.stat().st_size
                    path.unlink()
                if folder=='recordings':
                    db.delete(row)
                elif folder=='snapshots':
                    row.snapshot = None
                else:
                    row.clip_filename,row.clip_status = None,'expired'
            db.commit()
