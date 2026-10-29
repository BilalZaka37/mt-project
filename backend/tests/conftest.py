import os
import time

import cv2
import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import User
from app.main import create_app
from app.security import passwords


class TestDetector:
    """Deterministic boundary fixture, never exposed to the application UI."""
    def __init__(self, *_):
        self.frame = 0

    def detect(self, frame, confidence):
        self.frame += 1
        return [{'label': 'person', 'confidence': .93, 'track_id': 7,
                 'box': [30, 10, 70, 70] if self.frame > 2 else [1, 1, 10, 10]}]


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.setenv('MT_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MT_DATABASE_URL', '')
    config = Config('alembic.ini')
    command.upgrade(config, 'head')
    app = create_app(Settings(data_dir=tmp_path), detector_factory=TestDetector)
    with app.state.sessions() as db:
        for role in ('admin', 'operator', 'viewer'):
            db.add(User(email=f'{role}@example.test', password_hash=passwords.hash('test-password-1234'), role=role))
        db.commit()
    with TestClient(app, headers={'X-MT-Request': '1'}) as client:
        yield app, client


@pytest.fixture
def logged_in(application):
    app, client = application
    assert client.post('/api/auth/login', json={'email':'admin@example.test','password':'test-password-1234'}).status_code == 200
    return app, client


@pytest.fixture
def video(tmp_path):
    path = tmp_path/'source.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (160, 120))
    assert writer.isOpened()
    for i in range(24):
        frame = np.zeros((120,160,3), dtype=np.uint8)
        cv2.rectangle(frame, (i,20), (i+25,80), (120,190,220), -1)
        writer.write(frame)
    writer.release()
    return path


def wait_for(fn, timeout=10):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        value = fn()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('Timed out waiting for pipeline')
