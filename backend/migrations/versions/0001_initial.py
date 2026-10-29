"""MT Project initial schema. Immutable baseline; subsequent changes use new revisions."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users', sa.Column('id', sa.Integer, primary_key=True), sa.Column('email', sa.String(254), unique=True, nullable=False), sa.Column('password_hash', sa.Text, nullable=False), sa.Column('role', sa.String(16), nullable=False), sa.Column('active', sa.Boolean, nullable=False))
    op.create_table('sessions', sa.Column('token_hash', sa.String(64), primary_key=True), sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False), sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('cameras', sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(100), nullable=False), sa.Column('location', sa.String(100), nullable=False), sa.Column('kind', sa.String(16), nullable=False), sa.Column('source_encrypted', sa.Text, nullable=False), sa.Column('enabled', sa.Boolean, nullable=False), sa.Column('detection_enabled', sa.Boolean, nullable=False), sa.Column('recording_enabled', sa.Boolean, nullable=False), sa.Column('confidence', sa.Float, nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('zones', sa.Column('id', sa.Integer, primary_key=True), sa.Column('camera_id', sa.Integer, sa.ForeignKey('cameras.id', ondelete='CASCADE'), nullable=False), sa.Column('name', sa.String(100), nullable=False), sa.Column('points', sa.JSON, nullable=False), sa.Column('classes', sa.JSON, nullable=False))
    op.create_table('events', sa.Column('id', sa.Integer, primary_key=True), sa.Column('camera_id', sa.Integer, sa.ForeignKey('cameras.id', ondelete='CASCADE'), nullable=False), sa.Column('kind', sa.String(20), nullable=False), sa.Column('label', sa.String(100), nullable=False), sa.Column('confidence', sa.Float), sa.Column('track_id', sa.Integer), sa.Column('zone_name', sa.String(100)), sa.Column('snapshot', sa.String(100)), sa.Column('acknowledged', sa.Boolean, nullable=False), sa.Column('acknowledged_by', sa.Integer, sa.ForeignKey('users.id')), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('recordings', sa.Column('id', sa.Integer, primary_key=True), sa.Column('camera_id', sa.Integer, sa.ForeignKey('cameras.id', ondelete='CASCADE'), nullable=False), sa.Column('filename', sa.String(100), nullable=False), sa.Column('started_at', sa.DateTime(timezone=True), nullable=False), sa.Column('duration', sa.Float, nullable=False), sa.Column('size_bytes', sa.Integer, nullable=False))
    op.create_table('audit', sa.Column('id', sa.Integer, primary_key=True), sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id')), sa.Column('action', sa.String(100), nullable=False), sa.Column('target', sa.String(100), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    for table, cols in [('sessions',['expires_at']), ('zones',['camera_id']), ('events',['camera_id','kind','created_at']), ('recordings',['camera_id'])]:
        for col in cols:
            op.create_index(f'ix_{table}_{col}', table, [col])


def downgrade():
    for table in ['audit','recordings','events','zones','cameras','sessions','users']:
        op.drop_table(table)
