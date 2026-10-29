"""Dedicated disposable CI database only; skipped without MT_TEST_POSTGRES_URL."""
import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db import User
from app.main import create_app
from app.security import passwords


@pytest.mark.skipif(not os.getenv('MT_TEST_POSTGRES_URL'),reason='Requires dedicated PostgreSQL CI database')
def test_postgresql_migrations_and_authenticated_configuration(tmp_path,monkeypatch):
    url=os.environ['MT_TEST_POSTGRES_URL']
    assert make_url(url).database=='mt_project_ci','Use a dedicated database named mt_project_ci'
    monkeypatch.setenv('MT_DATABASE_URL',url)
    monkeypatch.setenv('MT_DATA_DIR',str(tmp_path))
    command.upgrade(Config('alembic.ini'),'head')
    command.check(Config('alembic.ini'))
    app=create_app(Settings(data_dir=tmp_path,database_url=url))
    with app.state.sessions() as db:
        if not db.scalar(select(User).where(User.email=='ci@example.test')):
            db.add(User(email='ci@example.test',password_hash=passwords.hash('ci-password-123456'),role='admin'))
            db.commit()
    with TestClient(app,headers={'X-MT-Request':'1'}) as client:
        assert client.post('/api/auth/login',json={'email':'ci@example.test','password':'ci-password-123456'}).status_code==200
        assert client.get('/api/system').json()['database']=='postgresql'
        response=client.post('/api/cameras',json={'name':'PostgreSQL validation','source':'rtsp://127.0.0.1/test'})
        assert response.status_code==201
        camera_id=response.json()['id']
        assert client.post(f'/api/cameras/{camera_id}/zones',json={'name':'Door','points':[[0,0],[1,0],[1,1],[0,1]]}).status_code==201
        assert len(client.get(f'/api/cameras/{camera_id}/zones').json())==1
        assert client.get('/api/events?since=2026-01-01T00:00:00Z').status_code==200
        assert client.delete(f'/api/cameras/{camera_id}').status_code==204
