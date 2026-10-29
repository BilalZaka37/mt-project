from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select, update

from .alerts import validate_destination
from .db import AlertDelivery, AlertEndpoint, DeliveryAttempt, utcnow
from .schemas import AlertEndpointInput, EndpointState


def register_alert_routes(app,settings,cipher,db_session,admin,operator,audit):
    def endpoint_dict(endpoint):
        return {'id':endpoint.id,'name':endpoint.name,'url':endpoint.url,'active':endpoint.active,'kinds':endpoint.kinds}

    @app.get('/api/alerts/endpoints')
    def endpoints(user=Depends(admin),db=Depends(db_session)):
        return {'items':[endpoint_dict(e) for e in db.scalars(select(AlertEndpoint).order_by(AlertEndpoint.id))],
                'allowed_hosts':settings.webhook_allowed_hosts,'local_http_allowed':settings.allow_local_webhooks}

    @app.post('/api/alerts/endpoints',status_code=201)
    def add_endpoint(payload:AlertEndpointInput,user=Depends(admin),db=Depends(db_session)):
        try:
            validate_destination(payload.url,settings)
        except ValueError as exc:
            raise HTTPException(422,str(exc))
        endpoint=AlertEndpoint(name=payload.name,url=payload.url,
            secret_encrypted=cipher.encrypt(payload.secret.encode()).decode(),kinds=payload.kinds)
        db.add(endpoint)
        db.flush()
        audit(db,user,'alert_endpoint.created',endpoint.id)
        db.commit()
        return endpoint_dict(endpoint)

    @app.patch('/api/alerts/endpoints/{endpoint_id}')
    def change_endpoint(endpoint_id:int,payload:EndpointState,user=Depends(admin),db=Depends(db_session)):
        endpoint=db.get(AlertEndpoint,endpoint_id)
        if not endpoint:
            raise HTTPException(404,'Alert destination not found')
        endpoint.active=payload.active
        audit(db,user,'alert_endpoint.resumed' if payload.active else 'alert_endpoint.paused',endpoint_id)
        db.commit()
        return endpoint_dict(endpoint)

    @app.get('/api/alerts/deliveries')
    def deliveries(status:str|None=None,limit:int=Query(25,ge=1,le=200),offset:int=Query(0,ge=0),
                   user=Depends(operator),db=Depends(db_session)):
        query=select(AlertDelivery,AlertEndpoint.name,AlertEndpoint.active).join(AlertEndpoint)
        if status:
            query=query.where(AlertDelivery.status==status)
        total=db.scalar(select(func.count()).select_from(query.subquery()))
        return {'total':total,'items':[{
            'id':d.id,'endpoint_id':d.endpoint_id,'endpoint_name':name,'endpoint_active':active,'event_id':d.event_id,'kind':d.payload['event']['kind'],
            'camera_name':d.payload['event']['camera_name'],'status':d.status,'attempts':d.attempts,
            'next_attempt_at':d.next_attempt_at,'last_error':d.last_error,'http_status':d.http_status,
            'delivered_at':d.delivered_at,'created_at':d.created_at}
            for d,name,active in db.execute(query.order_by(AlertDelivery.created_at.desc()).limit(limit).offset(offset))]}

    @app.post('/api/alerts/deliveries/{delivery_id}/retry')
    def retry(delivery_id:str,user=Depends(operator),db=Depends(db_session)):
        row=db.get(AlertDelivery,delivery_id)
        if not row:
            raise HTTPException(404,'Alert delivery not found')
        endpoint=db.get(AlertEndpoint,row.endpoint_id)
        if not endpoint.active:
            raise HTTPException(409,'Resume this alert destination before retrying')
        result=db.execute(update(AlertDelivery).where(AlertDelivery.id==delivery_id,AlertDelivery.status=='dead').values(
            status='pending',attempts=0,next_attempt_at=utcnow(),locked_until=None,last_error=None))
        if result.rowcount!=1:
            raise HTTPException(409,'Only failed deliveries can be retried manually')
        audit(db,user,'alert_delivery.retried',delivery_id)
        db.commit()
        return {'status':'pending'}

    @app.get('/api/alerts/deliveries/{delivery_id}/attempts')
    def attempts(delivery_id:str,user=Depends(operator),db=Depends(db_session)):
        if not db.get(AlertDelivery,delivery_id):
            raise HTTPException(404,'Alert delivery not found')
        return [{'number':a.attempt_number,'status':a.status,'started_at':a.started_at,
                 'finished_at':a.finished_at,'http_status':a.http_status,'error':a.error}
                for a in db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.delivery_id==delivery_id).order_by(DeliveryAttempt.id))]
