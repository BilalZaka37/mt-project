from pathlib import Path


class YOLODetector:
    """One model/tracker per camera: track IDs never leak across sources."""
    def __init__(self, model_path, device):
        if not model_path or not Path(model_path).is_file():
            raise RuntimeError('YOLO weights unavailable. Configure MT_MODEL_PATH with a local model file.')
        from ultralytics import YOLO
        self.model = YOLO(model_path)
        self.device = device

    def detect(self, frame, confidence):
        results = self.model.track(frame, persist=True, tracker='bytetrack.yaml',
                                   conf=confidence, device=self.device, verbose=False)[0]
        objects = []
        for box in results.boxes:
            objects.append({'label': results.names[int(box.cls.item())],
                            'confidence': float(box.conf.item()),
                            'track_id': int(box.id.item()) if box.id is not None else None,
                            'box': box.xyxy[0].tolist()})
        return objects

    def reset(self):
        for tracker in getattr(getattr(self.model, 'predictor', None), 'trackers', []):
            tracker.reset()
