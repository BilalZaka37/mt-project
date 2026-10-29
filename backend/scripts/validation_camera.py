"""Serve actual public footage as a loopback MJPEG source with deliberate outages.

This is a network test fixture, not a physical camera or fabricated video.
"""
import argparse
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.samples import fetch_sample


def main():
    parser=argparse.ArgumentParser(description='MT Project public-footage network fixture')
    parser.add_argument('--port',type=int,default=8791)
    parser.add_argument('--disconnect-after',type=float,default=8)
    args=parser.parse_args()
    source=fetch_sample(Settings())
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            if self.path!='/stream.mjpg':self.send_error(404);return
            self.send_response(200)
            self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            cap=cv2.VideoCapture(str(source))
            start=time.monotonic()
            try:
                while time.monotonic()-start<args.disconnect_after:
                    tick=time.monotonic()
                    ok,frame=cap.read()
                    if not ok:break
                    ok,jpeg=cv2.imencode('.jpg',frame)
                    if not ok:continue
                    data=jpeg.tobytes()
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n')
                    self.wfile.flush()
                    time.sleep(max(0,.1-(time.monotonic()-tick)))
            except (BrokenPipeError,ConnectionResetError):pass
            finally:cap.release()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'MT Project public-recording network fixture: http://127.0.0.1:{args.port}/stream.mjpg',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
