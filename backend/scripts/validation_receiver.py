"""MT Project loopback-only signed-webhook receiver for reproducible validation.

Set MT_RECEIVER_SECRET (32+ characters), then run this script. No external messages.
"""
import argparse
import hashlib
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='MT Project local alert receiver')
    parser.add_argument('--port',type=int,default=8790)
    parser.add_argument('--fail-first',type=int,default=1)
    parser.add_argument('--log',type=Path,default=Path('data/validation-deliveries.jsonl'))
    args=parser.parse_args()
    secret=os.getenv('MT_RECEIVER_SECRET','')
    if len(secret)<32:
        parser.error('Set MT_RECEIVER_SECRET to at least 32 characters')
    args.log.parent.mkdir(parents=True,exist_ok=True)
    log_lock=threading.Lock()
    state={'attempts':0,'seen':set()}
    if args.log.exists():
        for line in args.log.read_text(encoding='utf-8').splitlines():
            record=json.loads(line)
            if record.get('accepted'):
                state['seen'].add(record['delivery_id'])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_GET(self):
            if self.path!='/health':
                self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps({'product':'MT Project','purpose':'local validation receiver'}).encode())
        def do_POST(self):
            if self.path!='/events':
                self.send_error(404);return
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=1024*1024:
                self.send_error(413);return
            body=self.rfile.read(length)
            stamp=self.headers.get('X-MT-Timestamp','')
            signature=self.headers.get('X-MT-Signature','')
            expected='sha256='+hmac.new(secret.encode(),stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
            try:
                fresh=abs(time.time()-int(stamp))<300
                payload=json.loads(body)
            except (ValueError,TypeError):
                self.send_error(400);return
            if not fresh or not hmac.compare_digest(signature,expected):
                self.send_error(401);return
            delivery_id=self.headers.get('X-MT-Delivery','')
            if not delivery_id or delivery_id!=payload.get('delivery_id'):
                self.send_error(400);return
            with log_lock:
                state['attempts']+=1
                duplicate=delivery_id in state['seen']
                accepted=state['attempts']>args.fail_first or duplicate
                if accepted:state['seen'].add(delivery_id)
                record={'delivery_id':delivery_id,'accepted':accepted,'duplicate':duplicate,
                    'http_status':204 if accepted else 503,'received_at':time.time(),'payload':payload}
                with args.log.open('a',encoding='utf-8') as output:
                    output.write(json.dumps(record)+'\n')
            self.send_response(record['http_status']);self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'MT Project local receiver: http://127.0.0.1:{args.port}/events (first {args.fail_first} attempt(s) return 503)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__': main()
