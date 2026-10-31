export type User = { id: number; email: string; role: 'admin'|'operator'|'viewer'; active?: boolean }
export type Camera = { id: number; name: string; location: string; kind: string; enabled: boolean; status: string; detector: string; error: string|null; fps: number; objects: number; frame_age: number|null; detection_enabled: boolean; recording_enabled: boolean; confidence: number; readiness: string; capture_frames: number; inference_frames: number; inference_skipped: number; recording_frames: number; recording_dropped: number; recording_status: string; reconnects: number; last_seen: string|null; inference_age: number|null; provenance: {validation_only?:boolean;dataset?:string;source_url?:string} }
export type Event = { id: number; camera_id: number; camera_name: string; kind: string; label: string; confidence: number|null; track_id: number|null; zone_name: string|null; acknowledged: boolean; snapshot_url: string|null; created_at: string; details:{reason?:string;rule?:string;source_seconds?:number;recorded_source?:boolean}; clip_status:string;clip_url:string|null;clip_duration:number;clip_offset:number;clip_truncated:boolean;clip_error:string|null }
export type Recording = { id: number; camera_name: string; camera_id: number; started_at: string; duration: number; size_bytes: number; download_url: string; playback_url:string|null; format:string }
export type Zone = { id: number; name: string; points: [number,number][]; classes: string[] }
export type System = { product: string; version: string; database: string; model_available: boolean; device: string; max_cameras: number; retention_days: number; media_quota_mb: number; disk_free_bytes: number; upload_limit_mb: number; events: number; unacknowledged_intrusions: number }
export type Audit = { id: number; user_id: number; action: string; target: string; created_at: string }

export class ApiError extends Error { constructor(message: string, public status: number) { super(message) } }
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const form = body instanceof FormData
  const response = await fetch('/api'+path, {
    method, credentials: 'same-origin',
    headers: { 'X-MT-Request': '1', ...(!form && body !== undefined ? {'Content-Type':'application/json'} : {}) },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({detail:`Request failed (${response.status})`}))
    const detail = Array.isArray(data.detail) ? data.detail.map((e:{msg:string})=>e.msg).join('; ') : data.detail
    throw new ApiError(detail || 'Request failed', response.status)
  }
  return response.status === 204 ? undefined as T : response.json()
}

export function date(value: string) {
  return new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : value+'Z').toLocaleString(undefined, {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'})
}
export function bytes(value: number) { return value >= 1024**3 ? `${(value/1024**3).toFixed(1)} GB` : `${(value/1024**2).toFixed(1)} MB` }
