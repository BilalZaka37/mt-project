"""Durable, at-least-once webhook delivery. Receivers deduplicate X-MT-Delivery."""
import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import and_, func, or_, select, update

from .db import AlertDelivery, AlertEndpoint, DeliveryAttempt, utcnow

log = logging.getLogger('mt-project.alerts')


def validate_destination(url, settings):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if not host or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError('Use a webhook URL without credentials, query parameters, or fragments')
    if host not in settings.webhook_allowed_hosts:
        raise ValueError('Webhook host is not listed in MT_WEBHOOK_ALLOWED_HOSTS')
    local = host in ('localhost', '127.0.0.1', '::1')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local and settings.allow_local_webhooks):
        raise ValueError('HTTPS required; loopback HTTP requires MT_ALLOW_LOCAL_WEBHOOKS=true')
    return url


def enqueue_event(db, event, camera_name):
    """Called in the same transaction that persists the event."""
    db.flush()
    for endpoint in db.scalars(select(AlertEndpoint).where(AlertEndpoint.active.is_(True))):
        if event.kind in endpoint.kinds:
            delivery_id = uuid.uuid4().hex
            db.add(AlertDelivery(id=delivery_id, endpoint_id=endpoint.id, event_id=event.id,
                payload={'product':'MT Project', 'schema_version':1, 'delivery_id':delivery_id,
                         'event':{'id':event.id, 'camera_id':event.camera_id, 'camera_name':camera_name,
                                  'kind':event.kind, 'label':event.label, 'zone_name':event.zone_name,
                                  'confidence':event.confidence, 'track_id':event.track_id,
                                  'created_at':event.created_at.isoformat(), 'details':event.details,
                                  'snapshot_path':f'/api/events/{event.id}/snapshot' if event.snapshot else None,
                                  'evidence_path':f'/api/events/{event.id}/clip' if event.clip_status!='none' else None}}))


class AlertDispatcher:
    def __init__(self, settings, sessions, cipher, transport=None):
        self.settings, self.db, self.cipher = settings, sessions, cipher
        self.stop = threading.Event()
        self.thread = None
        self.transport = transport

    def start(self):
        self.thread = threading.Thread(target=self._run, name='mt-alert-delivery', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=25)

    @staticmethod
    def due(now):
        return or_(and_(AlertDelivery.status.in_(['pending','retry']), AlertDelivery.next_attempt_at<=now),
                   and_(AlertDelivery.status=='sending', AlertDelivery.locked_until<=now))

    def dispatch_once(self):
        now = utcnow()
        with self.db() as db:
            row = db.scalar(select(AlertDelivery).join(AlertEndpoint).where(
                AlertEndpoint.active.is_(True), self.due(now)).order_by(AlertDelivery.created_at).limit(1))
            if not row:
                return False
            delivery_id = row.id
            claimed = db.execute(update(AlertDelivery).where(AlertDelivery.id==delivery_id, self.due(now)).values(
                status='sending', locked_until=now+timedelta(seconds=60), attempts=AlertDelivery.attempts+1).execution_options(synchronize_session=False))
            if claimed.rowcount != 1:
                db.rollback()
                return True
            db.execute(update(DeliveryAttempt).where(DeliveryAttempt.delivery_id==delivery_id,
                DeliveryAttempt.status=='sending').values(status='unknown',finished_at=now,
                    error='Lease expired before outcome was persisted; receiver acceptance is unknown.'))
            cycle_attempt=row.attempts+1
            sequence=db.scalar(select(func.max(DeliveryAttempt.attempt_number)).where(DeliveryAttempt.delivery_id==delivery_id)) or 0
            attempt=DeliveryAttempt(delivery_id=delivery_id,attempt_number=sequence+1)
            db.add(attempt)
            db.flush()
            attempt_id,attempt_number=attempt.id,attempt.attempt_number
            db.commit()
            db.expire_all()
            row = db.get(AlertDelivery, delivery_id)
            endpoint = db.get(AlertEndpoint, row.endpoint_id)
            payload, url, encrypted = row.payload, endpoint.url, endpoint.secret_encrypted
        error, code = None, None
        try:
            validate_destination(url, self.settings)
            body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
            stamp = str(int(time.time()))
            secret = self.cipher.decrypt(encrypted.encode())
            signature = hmac.new(secret, stamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
            with httpx.Client(timeout=httpx.Timeout(5), follow_redirects=False, trust_env=False, transport=self.transport) as client:
                # Streaming avoids buffering an untrusted receiver's response body.
                with client.stream('POST', url, content=body, headers={'Content-Type':'application/json',
                    'User-Agent':'MT Project/0.2', 'X-MT-Delivery':delivery_id,
                    'X-MT-Timestamp':stamp, 'X-MT-Signature':'sha256='+signature}) as response:
                    code = response.status_code
                    if not 200 <= code < 300:
                        error = f'Receiver returned HTTP {code}'
        except Exception as exc:
            error = f'Delivery failed ({type(exc).__name__}); check receiver connectivity and server configuration.'
        with self.db() as db:
            row = db.get(AlertDelivery, delivery_id)
            attempt=db.get(DeliveryAttempt,attempt_id)
            if attempt:
                attempt.status='accepted' if error is None else 'failed'
                attempt.finished_at,attempt.http_status,attempt.error=utcnow(),code,error
            if row and row.attempts==cycle_attempt and row.status=='sending':
                row.http_status, row.last_error, row.locked_until = code, error, None
                if error is None:
                    row.status, row.delivered_at = 'delivered', utcnow()
                else:
                    permanent = code is not None and 400 <= code < 500 and code not in (408, 425, 429)
                    row.status = 'dead' if permanent or row.attempts>=6 else 'retry'
                    row.next_attempt_at = utcnow()+timedelta(seconds=min(3600, self.settings.retry_base_seconds*2**(row.attempts-1)))
            db.commit()
        return True

    def _run(self):
        while not self.stop.is_set():
            try:
                active = self.dispatch_once()
            except Exception:
                log.exception('Alert delivery worker failed')
                active = False
            self.stop.wait(.05 if active else .5)
