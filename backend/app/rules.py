import cv2
import numpy as np


def inside_zone(box, points, width, height):
    # Feet/bottom center, more useful for ground-plane intrusion than box center.
    point = ((box[0]+box[2]) / (2*width), box[3] / height)
    return cv2.pointPolygonTest(np.asarray(points, dtype=np.float32), point, False) >= 0


class AlertRules:
    def __init__(self):
        self.inside = set()
        self.last_event = {}

    def evaluate(self, objects, zones, width, height, now):
        alerts, current = [], set()
        self.last_event = {key: stamp for key, stamp in self.last_event.items() if now-stamp < 60}
        for obj in objects:
            track = obj['track_id']
            if track is None:
                continue
            key = ('detection', obj['label'], track)
            if not zones and now-self.last_event.get(key, -1e9) >= 15:
                alerts.append(('detection', obj, None))
                self.last_event[key] = now
            for zone in zones:
                if obj['label'] not in zone.classes or not inside_zone(obj['box'], zone.points, width, height):
                    continue
                key = ('intrusion', zone.id, track)
                current.add(key)
                if key not in self.inside and now-self.last_event.get(key, -1e9) >= 15:
                    alerts.append(('intrusion', obj, zone.name))
                    self.last_event[key] = now
        self.inside = current
        return alerts


