import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('MT_DATA_DIR', 'data')).resolve())
    database_url: str = field(default_factory=lambda: os.getenv('MT_DATABASE_URL', ''))
    secure_cookie: bool = field(default_factory=lambda: os.getenv('MT_SECURE_COOKIE', 'false').lower() == 'true')
    model_path: str = field(default_factory=lambda: os.getenv('MT_MODEL_PATH', ''))
    device: str = field(default_factory=lambda: os.getenv('MT_DEVICE', 'cpu'))
    max_cameras: int = field(default_factory=lambda: int(os.getenv('MT_MAX_CAMERAS', '8')))
    upload_limit: int = field(default_factory=lambda: int(os.getenv('MT_UPLOAD_MB', '512')) * 1024 * 1024)
    retention_days: int = field(default_factory=lambda: int(os.getenv('MT_RETENTION_DAYS', '7')))
    media_quota_mb: int = field(default_factory=lambda: int(os.getenv('MT_MEDIA_QUOTA_MB', '10240')))
    segment_seconds: float = field(default_factory=lambda: float(os.getenv('MT_SEGMENT_SECONDS', '30')))
    clip_pre_seconds: float = field(default_factory=lambda: float(os.getenv('MT_CLIP_PRE_SECONDS', '3')))
    clip_post_seconds: float = field(default_factory=lambda: float(os.getenv('MT_CLIP_POST_SECONDS', '5')))
    retry_base_seconds: float = field(default_factory=lambda: float(os.getenv('MT_ALERT_RETRY_SECONDS', '5')))
    webhook_allowed_hosts: tuple = field(default_factory=lambda: tuple(h.strip().lower() for h in os.getenv('MT_WEBHOOK_ALLOWED_HOSTS', '').split(',') if h.strip()))
    allow_local_webhooks: bool = field(default_factory=lambda: os.getenv('MT_ALLOW_LOCAL_WEBHOOKS', 'false').lower() == 'true')

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not 1 <= self.segment_seconds <= 300 or not 0 <= self.clip_pre_seconds <= 10 or not 0 <= self.clip_post_seconds <= 15:
            raise ValueError('Invalid MT Project recording/clip duration settings')
        for name in ('uploads', 'snapshots', 'recordings', 'clips', 'samples'):
            (self.data_dir / name).mkdir(exist_ok=True)
        if not self.database_url:
            self.database_url = 'sqlite:///' + (self.data_dir / 'mt-project.db').as_posix()

