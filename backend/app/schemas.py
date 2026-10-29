import math
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class NewUser(Login):
    password: str = Field(min_length=12, max_length=256)
    role: Literal['admin', 'operator', 'viewer'] = 'viewer'

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if '@' not in value or ' ' in value:
            raise ValueError('Enter a valid email address')
        return value


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class CameraInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(default='', max_length=100)
    source: str = Field(min_length=1, max_length=2048)
    detection_enabled: bool = True
    recording_enabled: bool = False
    confidence: float = Field(default=0.45, ge=0.1, le=0.95)

    @field_validator('source')
    @classmethod
    def source_url(cls, value):
        parts = urlsplit(value)
        if parts.scheme not in ('rtsp', 'rtsps', 'http', 'https') or not parts.hostname:
            raise ValueError('Use an RTSP or HTTP(S) camera URL; upload files separately')
        if any(c in value for c in ('\n', '\r', '\x00')):
            raise ValueError('Invalid source URL')
        # Private network cameras are intentional. Only administrators can add sources.
        return value


class CameraUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(default='', max_length=100)
    detection_enabled: bool
    recording_enabled: bool
    confidence: float = Field(ge=0.1, le=0.95)


class ZoneInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    points: list[tuple[float, float]] = Field(min_length=3, max_length=32)
    classes: list[str] = Field(default_factory=lambda: ['person'], min_length=1, max_length=80)

    @field_validator('points')
    @classmethod
    def valid_polygon(cls, points):
        if any(not math.isfinite(n) or not 0 <= n <= 1 for point in points for n in point):
            raise ValueError('Zone coordinates must be normalized between 0 and 1')
        if len(set(points)) != len(points):
            raise ValueError('Zone vertices must be distinct')
        area = abs(sum(a[0]*b[1] - b[0]*a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2
        if area < 0.0001:
            raise ValueError('Zone must have nonzero area')
        def cross(a, b, c):
            return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        edges = list(zip(points, points[1:] + points[:1]))
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges):
                if j <= i or j == i+1 or (i == 0 and j == len(edges)-1):
                    continue
                if cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0:
                    raise ValueError('Zone edges must not intersect')
        return points


class AlertEndpointInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    url: str = Field(min_length=8,max_length=2048)
    secret: str = Field(min_length=32,max_length=256)
    kinds: list[Literal['intrusion','detection','snapshot','offline','recovered']] = Field(
        default_factory=lambda:['intrusion','offline','recovered'], min_length=1,max_length=5)


class EndpointState(BaseModel):
    active: bool
