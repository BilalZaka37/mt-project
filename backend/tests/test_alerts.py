import hashlib
import hmac
import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.alerts import AlertDispatcher, enqueue_event, validate_destination
from app.db import AlertDelivery, AlertEndpoint, DeliveryAttempt, Event, utcnow
from test_api import login

SECRET='mt-project-test-secret-at-least-32-characters'


def setup_delivery(app,client,url='http://127.0.0.1:9876/events'):
    app.state.dispatcher.close()
    app.state.settings.webhook_allowed_hosts=('127.0.0.1',)
    app.state.settings.allow_local_webhooks=True
    response=client.post('/api/alerts/endpoints',json={'name':'Test receiver','url':url,'secret':SECRET,'kinds':['intrusion']})
    assert response.status_code==201,response.text
    assert SECRET not in response.text
    camera_id=client.post('/api/cameras',json={'name':'Door','source':'rtsp://127.0.0.1/test'}).json()['id']
    with app.state.sessions() as db:
        event=Event(camera_id=camera_id,kind='intrusion',label='person',zone_name='Door')
        db.add(event);enqueue_event(db,event,'Door');db.commit()
        delivery=db.scalar(select(AlertDelivery))
        endpoint=db.get(AlertEndpoint,delivery.endpoint_id)
        assert SECRET not in endpoint.secret_encrypted
        return delivery.id,endpoint.id


def make_due(app,delivery_id):
    with app.state.sessions() as db:
        row=db.get(AlertDelivery,delivery_id);row.next_attempt_at=utcnow()-timedelta(seconds=1);db.commit()


def test_real_http_failure_then_success_signed_payload_and_persistent_retry(logged_in):
    app,client=logged_in
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_POST(self):
            body=self.rfile.read(int(self.headers['Content-Length']))
            signature=hmac.new(SECRET.encode(),self.headers['X-MT-Timestamp'].encode()+b'.'+body,hashlib.sha256).hexdigest()
            assert hmac.compare_digest(self.headers['X-MT-Signature'],'sha256='+signature)
            received.append((self.headers['X-MT-Delivery'],json.loads(body)))
            self.send_response(503 if len(received)==1 else 204);self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        delivery_id,_=setup_delivery(app,client,f'http://127.0.0.1:{server.server_port}/events')
        dispatcher=AlertDispatcher(app.state.settings,app.state.sessions,app.state.cipher)
        assert dispatcher.dispatch_once()
        with app.state.sessions() as db:
            row=db.get(AlertDelivery,delivery_id)
            assert row.status=='retry' and row.attempts==1 and row.http_status==503
        make_due(app,delivery_id)
        # A new dispatcher instance demonstrates that retry state survives worker replacement.
        restarted=AlertDispatcher(app.state.settings,app.state.sessions,app.state.cipher)
        assert restarted.dispatch_once()
        with app.state.sessions() as db:
            row=db.get(AlertDelivery,delivery_id)
            assert row.status=='delivered' and row.attempts==2 and row.delivered_at
        assert received[0][0]==received[1][0]==delivery_id
        assert received[0][1]==received[1][1]
        assert received[1][1]['product']=='MT Project'
        attempts=client.get(f'/api/alerts/deliveries/{delivery_id}/attempts').json()
        assert [a['status'] for a in attempts]==['failed','accepted']
        assert [a['http_status'] for a in attempts]==[503,204]
        assert not restarted.dispatch_once()
    finally:
        server.shutdown();server.server_close();worker.join(timeout=2)


def test_permanent_failure_dead_letter_pause_and_manual_retry(logged_in):
    app,client=logged_in
    delivery_id,endpoint_id=setup_delivery(app,client)
    transport=httpx.MockTransport(lambda request:httpx.Response(400))
    dispatcher=AlertDispatcher(app.state.settings,app.state.sessions,app.state.cipher,transport=transport)
    dispatcher.dispatch_once()
    assert client.get('/api/alerts/deliveries?status=dead').json()['total']==1
    assert client.patch(f'/api/alerts/endpoints/{endpoint_id}',json={'active':False}).status_code==200
    assert client.post(f'/api/alerts/deliveries/{delivery_id}/retry').status_code==409
    client.patch(f'/api/alerts/endpoints/{endpoint_id}',json={'active':True})
    assert client.post(f'/api/alerts/deliveries/{delivery_id}/retry').status_code==200
    assert client.post(f'/api/alerts/deliveries/{delivery_id}/retry').status_code==409
    dispatcher.transport=httpx.MockTransport(lambda request:httpx.Response(204))
    dispatcher.dispatch_once()
    assert client.get('/api/alerts/deliveries?status=delivered').json()['total']==1


def test_expired_delivery_lease_is_recovered(logged_in):
    app,client=logged_in
    delivery_id,_=setup_delivery(app,client)
    with app.state.sessions() as db:
        row=db.get(AlertDelivery,delivery_id)
        row.status='sending';row.attempts=1;row.locked_until=utcnow()-timedelta(seconds=2)
        db.add(DeliveryAttempt(delivery_id=delivery_id,attempt_number=1));db.commit()
    dispatcher=AlertDispatcher(app.state.settings,app.state.sessions,app.state.cipher,
        transport=httpx.MockTransport(lambda request:httpx.Response(200)))
    assert dispatcher.dispatch_once()
    assert client.get('/api/alerts/deliveries').json()['items'][0]['status']=='delivered'
    assert [a['status'] for a in client.get(f'/api/alerts/deliveries/{delivery_id}/attempts').json()]==['unknown','accepted']


def test_retry_limit_stops_repeated_failure(logged_in):
    app,client=logged_in
    delivery_id,_=setup_delivery(app,client)
    dispatcher=AlertDispatcher(app.state.settings,app.state.sessions,app.state.cipher,
        transport=httpx.MockTransport(lambda request:httpx.Response(503)))
    for _ in range(6):
        make_due(app,delivery_id)
        assert dispatcher.dispatch_once()
    result=client.get('/api/alerts/deliveries').json()['items'][0]
    assert result['status']=='dead' and result['attempts']==6
    assert not dispatcher.dispatch_once()


def test_outbox_is_atomic_with_event_transaction(logged_in):
    app,client=logged_in
    _,_=setup_delivery(app,client)
    with app.state.sessions() as db:
        before=len(list(db.scalars(select(AlertDelivery))))
        event=Event(camera_id=999999,kind='intrusion',label='person')
        db.add(event)
        with pytest.raises(IntegrityError):
            enqueue_event(db,event,'Invalid')
            db.commit()
        db.rollback()
        assert len(list(db.scalars(select(AlertDelivery))))==before


def test_webhook_configuration_permissions_and_host_restrictions(logged_in):
    app,client=logged_in
    app.state.settings.webhook_allowed_hosts=('127.0.0.1',)
    for url in ['https://unlisted.example/events','http://127.0.0.1/events','https://user:password@127.0.0.1/events',
                'https://127.0.0.1/events?token=secret']:
        result=client.post('/api/alerts/endpoints',json={'name':'Rejected','url':url,'secret':SECRET})
        assert result.status_code==422
    login(client,'operator')
    assert client.get('/api/alerts/deliveries').status_code==200
    assert client.get('/api/alerts/endpoints').status_code==403
    login(client,'viewer')
    assert client.get('/api/alerts/deliveries').status_code==403
