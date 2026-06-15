// Thin client for the collajit FastAPI backend.
// The backend allows CORS from localhost, so we call it by absolute URL in both
// browser-dev and Tauri. Override with VITE_API_BASE if you run it elsewhere.

const API_BASE =
  (import.meta as any).env?.VITE_API_BASE ?? "http://127.0.0.1:8756";

/** Prefix a backend-relative asset path (thumb/output/upload) for use in <img>. */
export const asset = (p: string): string =>
  p.startsWith("http") ? p : API_BASE + p;

export interface LibImage {
  id: string;
  name: string;
  thumb_url: string;
  width: number;
  height: number;
  aspect: number;
}
export interface Library {
  count: number;
  images: LibImage[];
}
export interface JobSnap {
  id: string;
  label: string;
  status: "pending" | "running" | "done" | "error";
  done: number;
  total: number;
  result: any;
  error: string | null;
  logs: string[];
}

async function jget(path: string) {
  const r = await fetch(API_BASE + path);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function jpost(path: string, body?: unknown) {
  const r = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((d) => d.detail)
      .catch(() => r.statusText);
    throw new Error(detail || r.statusText);
  }
  return r.json();
}

export const api = {
  health: () => jget("/api/health"),
  library: (): Promise<Library> => jget("/api/library"),
  addFolder: (path: string) => jpost("/api/library/folder", { path }),
  clear: () => jpost("/api/library/clear"),
  suggest: (target_path: string): Promise<{ terms: string[] }> =>
    jpost("/api/suggest", { target_path }),
  fetch: (body: unknown) => jpost("/api/fetch", body),
  mosaic: (body: unknown) => jpost("/api/mosaic", body),
  generative: (body: unknown) => jpost("/api/generative", body),
  save: (name: string, dest: string) => jpost("/api/save", { name, dest }),
  openOutput: (name: string) => jpost("/api/open_output", { name }),
  async upload(file: File): Promise<{ path: string; url: string }> {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(API_BASE + "/api/upload", { method: "POST", body: fd });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
};

/** Subscribe to a job's SSE stream; resolves on done, rejects on error. */
export function runJob(
  jobId: string,
  onProgress: (j: JobSnap) => void
): Promise<JobSnap> {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`${API_BASE}/api/jobs/${jobId}/events`);
    es.onmessage = (e) => {
      const j: JobSnap = JSON.parse(e.data);
      onProgress(j);
      if (j.status === "done") {
        es.close();
        resolve(j);
      } else if (j.status === "error") {
        es.close();
        reject(new Error(j.error || "job failed"));
      }
    };
    es.onerror = () => {
      es.close();
      reject(new Error("lost connection to backend"));
    };
  });
}
