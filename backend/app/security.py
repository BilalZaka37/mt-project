import hashlib
import os
import secrets
from datetime import timedelta

from cryptography.fernet import Fernet
from pwdlib import PasswordHash
from sqlalchemy import delete

from .db import Session, utcnow

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash(secrets.token_urlsafe(24))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(db, user):
    db.execute(delete(Session).where(Session.expires_at < utcnow()))
    token = secrets.token_urlsafe(48)
    db.add(Session(token_hash=token_hash(token), user_id=user.id, expires_at=utcnow() + timedelta(hours=12)))
    return token


def cipher(settings):
    key = os.getenv('MT_ENCRYPTION_KEY')
    if not key:
        path = settings.data_dir / '.encryption-key'
        if not path.exists():
            try:
                with path.open('xb') as output:
                    output.write(Fernet.generate_key())
                path.chmod(0o600)
            except FileExistsError:
                pass
        key = path.read_bytes()
    return Fernet(key)

