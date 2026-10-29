import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.samples import PROVENANCE, fetch_sample

if __name__=='__main__':
    path=fetch_sample(Settings())
    print('MT Project: verified public validation recording:',path)
    print('Source:',PROVENANCE['source_url'])
    print('This is recorded test footage, not a physical camera.')
