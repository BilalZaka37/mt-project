import argparse
import getpass

from sqlalchemy import select

from .config import Settings
from .db import User, connect
from .schemas import NewUser
from .security import passwords


def main():
    parser = argparse.ArgumentParser(description='MT Project administration')
    parser.add_argument('command', choices=['create-admin'])
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    password = getpass.getpass('MT Project password (at least 12 characters): ')
    if password != getpass.getpass('Confirm password: '):
        parser.error('Passwords do not match')
    payload = NewUser(email=args.email, password=password, role='admin')
    engine, factory = connect(Settings().database_url)
    with factory() as db:
        if db.scalar(select(User).where(User.email == payload.email)):
            parser.error('User already exists')
        db.add(User(email=payload.email, password_hash=passwords.hash(payload.password), role='admin'))
        db.commit()
    engine.dispose()
    print('MT Project administrator created.')


if __name__ == '__main__':
    main()
