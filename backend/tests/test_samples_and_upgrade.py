import hashlib
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app import samples
from app.config import Settings
from app.db import Camera, Event, connect


def test_public_sample_import_is_explicit_attributed_and_admin_only(logged_in,video,monkeypatch):
    app,client=logged_in
    monkeypatch.setattr('app.main.fetch_sample',lambda settings:video)
    response=client.post('/api/cameras/sample')
    assert response.status_code==201
    camera=response.json()
    assert camera['provenance']['validation_only'] is True
    assert 'opencv' in camera['provenance']['source_url']
    assert camera['enabled'] is False and camera['recording_enabled'] is True
    assert len(client.get(f"/api/cameras/{camera['id']}/zones").json())==1
    client.post('/api/auth/login',json={'email':'viewer@example.test','password':'test-password-1234'})
    assert client.post('/api/cameras/sample').status_code==403


def test_sample_fetch_verifies_download_and_cached_bytes(tmp_path,video,monkeypatch):
    settings=Settings(data_dir=tmp_path/'data')
    monkeypatch.setattr(samples,'URL',video.as_uri())
    monkeypatch.setattr(samples,'SHA256',hashlib.sha256(video.read_bytes()).hexdigest())
    path=samples.fetch_sample(settings)
    assert path.read_bytes()==video.read_bytes()
    assert samples.fetch_sample(settings)==path
    path.write_bytes(b'corrupted')
    with pytest.raises(RuntimeError,match='checksum'):
        samples.fetch_sample(settings)


def test_failed_sample_checksum_never_publishes_partial_file(tmp_path,video,monkeypatch):
    settings=Settings(data_dir=tmp_path/'data')
    monkeypatch.setattr(samples,'URL',video.as_uri())
    monkeypatch.setattr(samples,'SHA256','0'*64)
    with pytest.raises(RuntimeError,match='checksum'):
        samples.fetch_sample(settings)
    assert not list((settings.data_dir/'samples').iterdir())


def test_v01_database_upgrade_preserves_camera_and_event(tmp_path,monkeypatch):
    monkeypatch.setenv('MT_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('MT_DATABASE_URL','')
    config=Config('alembic.ini')
    command.upgrade(config,'0001')
    engine,sessions=connect(Settings().database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO cameras(id,name,location,kind,source_encrypted,enabled,detection_enabled,recording_enabled,confidence,created_at) VALUES (1,'Existing camera','Old site','file','encrypted-source',false,true,false,0.45,CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO events(id,camera_id,kind,label,acknowledged,created_at) VALUES (1,1,'intrusion','person',false,CURRENT_TIMESTAMP)"))
    command.upgrade(config,'head')
    command.check(config)
    with sessions() as db:
        assert db.get(Camera,1).name=='Existing camera'
        assert db.get(Camera,1).source_encrypted=='encrypted-source'
        assert db.get(Camera,1).provenance=={}
        event=db.get(Event,1)
        assert event.label=='person' and event.clip_status=='none' and event.details=={}
    engine.dispose()
