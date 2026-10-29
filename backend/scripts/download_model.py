"""MT Project explicit, checksum-pinned download of official YOLO11n weights."""
import hashlib
import os
import urllib.request
from pathlib import Path

URL = 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt'
SHA256 = '0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1'


def main():
    directory = Path(os.getenv('MT_DATA_DIR', 'data')).resolve()/'models'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory/'yolo11n.pt'
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != SHA256:
            raise SystemExit('Existing model does not match the pinned checksum. Move it aside and retry.')
    else:
        temporary = directory/'yolo11n.pt.part'
        try:
            print('MT Project: downloading official YOLO11n weights. See docs/THIRD_PARTY.md for licensing.')
            with urllib.request.urlopen(URL, timeout=120) as response, temporary.open('wb') as output:
                while chunk := response.read(1024*1024):
                    output.write(chunk)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
                raise SystemExit('Model checksum mismatch; download rejected.')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    print(f'MT Project model verified: {target}')
    print('Set MT_MODEL_PATH to this absolute path, then restart the camera worker.')


if __name__ == '__main__':
    main()
