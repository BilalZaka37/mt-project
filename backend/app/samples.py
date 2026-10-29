"""Public validation footage, explicitly separate from connected physical cameras."""
import hashlib
import threading
import urllib.request
import uuid

URL = 'https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi'
SHA256 = '45cddc9490be69345cbdab64ca583be65987e864ca408038e648db99e10516cf'
PROVENANCE = {'dataset':'OpenCV pedestrian sample (vtest.avi)', 'source_url':URL, 'sha256':SHA256,
    'validation_only':True, 'description':'Public recorded test footage; not a physical camera or footage filmed by MT Project.'}
download_lock = threading.Lock()


def fetch_sample(settings):
    target = settings.data_dir/'samples'/'opencv-pedestrians.avi'
    with download_lock:
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=SHA256:
                raise RuntimeError('Cached validation footage failed its checksum. Remove the file and download again.')
            return target
        temporary=target.with_suffix('.'+uuid.uuid4().hex+'.part')
        try:
            with urllib.request.urlopen(URL,timeout=30) as source, temporary.open('wb') as output:
                total=0
                while chunk:=source.read(1024*1024):
                    total+=len(chunk)
                    if total>16*1024*1024:
                        raise RuntimeError('Validation download exceeded its expected size')
                    output.write(chunk)
            if hashlib.sha256(temporary.read_bytes()).hexdigest()!=SHA256:
                raise RuntimeError('Validation footage checksum mismatch')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return target
