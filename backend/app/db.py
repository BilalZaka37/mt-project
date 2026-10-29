from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default='viewer')
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Session(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Camera(Base):
    __tablename__ = 'cameras'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(100), default='')
    kind: Mapped[str] = mapped_column(String(16))
    source_encrypted: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    detection_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.45)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)


class Zone(Base):
    __tablename__ = 'zones'
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey('cameras.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    points: Mapped[list] = mapped_column(JSON)
    classes: Mapped[list] = mapped_column(JSON, default=lambda: ['person'])


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey('cameras.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    clip_status: Mapped[str] = mapped_column(String(20), default='none')
    clip_filename: Mapped[str | None] = mapped_column(String(100), nullable=True)
    clip_duration: Mapped[float] = mapped_column(Float, default=0)
    clip_offset: Mapped[float] = mapped_column(Float, default=0)
    clip_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    clip_error: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Recording(Base):
    __tablename__ = 'recordings'
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey('cameras.id', ondelete='CASCADE'), index=True)
    filename: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration: Mapped[float] = mapped_column(Float)
    size_bytes: Mapped[int] = mapped_column(Integer)


class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertEndpoint(Base):
    __tablename__ = 'alert_endpoints'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(2048))
    secret_encrypted: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    kinds: Mapped[list] = mapped_column(JSON, default=lambda: ['intrusion', 'offline', 'recovered'])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertDelivery(Base):
    __tablename__ = 'alert_deliveries'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey('alert_endpoints.id', ondelete='CASCADE'), index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey('events.id', ondelete='SET NULL'), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeliveryAttempt(Base):
    __tablename__ = 'delivery_attempts'
    __table_args__ = (UniqueConstraint('delivery_id','attempt_number',name='uq_delivery_attempt_number'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[str] = mapped_column(ForeignKey('alert_deliveries.id',ondelete='CASCADE'),index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20),default='sending')
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer,nullable=True)
    error: Mapped[str | None] = mapped_column(String(200),nullable=True)


def connect(url):
    engine = create_engine(url, connect_args={'check_same_thread': False} if url.startswith('sqlite') else {}, pool_pre_ping=True)
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def pragmas(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
    return engine, sessionmaker(engine, expire_on_commit=False)

