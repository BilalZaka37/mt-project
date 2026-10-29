"""Bounded, independent recording and incident-evidence encoding."""
import logging
import os
import queue
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime

import cv2
import imageio_ffmpeg
import numpy as np

from .db import Camera, Event, Recording

log = logging.getLogger('mt-project.media')


@dataclass(frozen=True)
class FramePacket:
    seq: int
    clock: float
    captured_at: datetime
    received_at: float
    jpeg: bytes
    generation: int = 0


def decode(packet):
    frame = cv2.imdecode(np.frombuffer(packet.jpeg, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError('Unable to decode captured frame')
    return frame[:frame.shape[0]//2*2, :frame.shape[1]//2*2]


class MP4Writer:
    def __init__(self, path, frame, fps=10):
        self.path, self.frames, self.fps = path, 0, fps
        self.temporary = path.with_suffix('.mp4.part')
        height, width = frame.shape[:2]
        command = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
                   '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', str(fps),
                   '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-threads', '1', '-preset', 'ultrafast',
                   '-crf', '23', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-f', 'mp4', str(self.temporary)]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)

    def write(self, frame):
        self.process.stdin.write(frame.tobytes())
        self.frames += 1

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
            self.process.stdin = None
        try:
            _, stderr = self.process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate()
            self.temporary.unlink(missing_ok=True)
            raise RuntimeError('MP4 encoder timed out')
        if self.process.returncode or not self.frames:
            self.temporary.unlink(missing_ok=True)
            raise RuntimeError('MP4 encoder failed')
        self.temporary.replace(self.path)
        return self.frames/self.fps

    def abort(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.communicate()
        self.temporary.unlink(missing_ok=True)


class SegmentRecorder:
    """Capture pushes JPEGs; the recorder owns the encoder and a bounded queue."""
    def __init__(self, camera_id, settings, sessions, runtime):
        self.camera_id, self.settings, self.db, self.runtime = camera_id, settings, sessions, runtime
        self.queue = queue.Queue(maxsize=64)
        self.thread = threading.Thread(target=self._run, name=f'mt-record-{camera_id}', daemon=True)
        self.thread.start()

    def push(self, packet):
        if self.runtime.recording_status == 'failed':
            return
        try:
            self.queue.put_nowait(packet)
        except queue.Full:
            self.runtime.recording_dropped += 1

    def discontinuity(self):
        # This marker shares ordering with frames. No recording spans a reconnect.
        self.queue.put('discontinuity', timeout=10)

    def finish(self):
        if self.thread.is_alive():
            self.queue.put(None, timeout=10)
            self.thread.join(timeout=40)
            if self.thread.is_alive():
                self.runtime.recording_status = 'failed'
                self.runtime.recording_error = 'Recording finalization did not finish in time.'

    def _run(self):
        writer, first = None, None
        def finish_segment():
            nonlocal writer
            if writer:
                self.runtime.recording_status = 'finalizing'
                duration = writer.close()
                with self.db() as db:
                    if db.get(Camera, self.camera_id):
                        db.add(Recording(camera_id=self.camera_id, filename=writer.path.name,
                            started_at=first.captured_at, duration=duration, size_bytes=writer.path.stat().st_size))
                        db.commit()
                    else:
                        writer.path.unlink(missing_ok=True)
                writer = None
        try:
            self.runtime.recording_status = 'waiting'
            while True:
                packet = self.queue.get()
                if packet is None:
                    break
                if packet == 'discontinuity':
                    finish_segment()
                    continue
                if writer and packet.clock-first.clock >= self.settings.segment_seconds:
                    finish_segment()
                frame = decode(packet)
                if writer is None:
                    first = packet
                    writer = MP4Writer(self.settings.data_dir/'recordings'/(uuid.uuid4().hex+'.mp4'), frame)
                self.runtime.recording_status = 'recording'
                target = min(int((packet.clock-first.clock)*10+1e-6)+1, int(self.settings.segment_seconds*10))
                while writer.frames < target:
                    writer.write(frame)
                    self.runtime.recording_frames += 1
            finish_segment()
            self.runtime.recording_status = 'finalized'
        except Exception:
            log.exception('Recording failed for camera %s', self.camera_id)
            if writer:
                writer.abort()
            self.runtime.recording_status = 'failed'
            self.runtime.recording_error = 'Recording failed. Check encoder, disk space, and server logs.'
            # Drain so finish/discontinuity cannot deadlock a full queue after failure.
            while not self.queue.empty():
                self.queue.get_nowait()


class IncidentEncoder:
    def __init__(self, settings, sessions):
        self.settings, self.db = settings, sessions
        self.queue = queue.Queue(maxsize=16)
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        # Buffers are in memory; an interrupted clip is explicit, never shown as ready.
        with self.db() as db:
            for event in db.query(Event).filter(Event.clip_status.in_(['collecting','queued','encoding'])):
                event.clip_status = 'failed'
                event.clip_error = 'Clip interrupted by a server restart. Snapshot evidence remains available.'
            db.commit()
        self.thread = threading.Thread(target=self._run, name='mt-incident-clips', daemon=True)
        self.thread.start()

    def submit(self, event_id, packets, trigger_clock, truncated):
        with self.db() as db:
            event = db.get(Event, event_id)
            if not event:
                return
            event.clip_status = 'queued'
            db.commit()
        try:
            self.queue.put_nowait((event_id, packets, trigger_clock, truncated))
        except queue.Full:
            self.fail(event_id, 'Incident encoder capacity reached; snapshot evidence is retained.')

    def fail(self, event_id, error):
        with self.db() as db:
            event = db.get(Event, event_id)
            if event:
                event.clip_status, event.clip_error = 'failed', error
                db.commit()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=45)

    def _run(self):
        while not self.stop.is_set() or not self.queue.empty():
            try:
                job = self.queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                self.encode(*job)
            finally:
                self.queue.task_done()

    def encode(self, event_id, packets, trigger_clock, truncated):
        path = self.settings.data_dir/'clips'/(uuid.uuid4().hex+'.mp4')
        writer = None
        try:
            if not packets:
                raise RuntimeError('No captured frames available for incident')
            packets = sorted({p.seq:p for p in packets}.values(), key=lambda p:p.clock)
            with self.db() as db:
                event = db.get(Event, event_id)
                if not event:
                    return
                event.clip_status = 'encoding'
                db.commit()
            writer = MP4Writer(path, decode(packets[0]))
            first_clock = packets[0].clock
            for packet in packets:
                target = int((packet.clock-first_clock)*10+1e-6)+1
                frame = decode(packet)
                while writer.frames < target:
                    writer.write(frame)
            duration = writer.close()
            with self.db() as db:
                event = db.get(Event, event_id)
                if event:
                    event.clip_status, event.clip_filename = 'ready', path.name
                    event.clip_duration = duration
                    event.clip_offset = max(0, trigger_clock-first_clock)
                    event.clip_truncated = truncated
                    db.commit()
                else:
                    path.unlink(missing_ok=True)
        except Exception:
            log.exception('Incident clip %s failed', event_id)
            if writer and writer.process.poll() is None:
                writer.abort()
            path.unlink(missing_ok=True)
            self.fail(event_id, 'Incident encoding failed. Check encoder and disk space.')
