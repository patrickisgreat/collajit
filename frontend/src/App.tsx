import { useEffect, useRef, useState } from "react";
import { open as openDialog, save as saveDialog } from "@tauri-apps/plugin-dialog";
import {
  api,
  asset,
  runJob,
  type JobSnap,
  type Library,
  type LibImage,
} from "./api";
import { physicalGrid } from "./helpers";

const IS_TAURI =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type Target = { path: string; url: string } | null;

/** useState that persists to localStorage (survives app restarts). */
function usePersistedState<T>(key: string, initial: T) {
  const k = "collajit:" + key;
  const [val, setVal] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(k);
      return raw != null ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(k, JSON.stringify(val));
    } catch {
      /* ignore quota/serialization errors */
    }
  }, [k, val]);
  return [val, setVal] as const;
}

export default function App() {
  const [lib, setLib] = useState<Library>({ count: 0, images: [] });
  const [sources, setSources] = useState<string[]>([]);
  const [tab, setTab] = usePersistedState<"mosaic" | "fetch" | "generative">("tab", "mosaic");
  const [target, setTarget] = usePersistedState<Target>("target", null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<JobSnap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [result, setResult] = useState<{ url: string; info: any } | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [lastFolder, setLastFolder] = usePersistedState("lastFolder", "");
  const [dialog, setDialog] = useState<DialogState | null>(null);

  // In-app confirm/prompt — window.confirm/prompt are no-ops in the Tauri webview.
  const askConfirm = (message: string) =>
    new Promise<boolean>((resolve) => setDialog({ kind: "confirm", message, resolve }));
  const askPrompt = (message: string, value = "") =>
    new Promise<string | null>((resolve) =>
      setDialog({ kind: "prompt", message, value, resolve })
    );

  const refreshLib = () => api.library().then(setLib).catch(() => {});

  useEffect(() => {
    // The desktop shell spawns the backend at launch; retry until it answers.
    let cancelled = false;
    (async () => {
      for (let i = 0; i < 40 && !cancelled; i++) {
        try {
          const h = await api.health();
          if (cancelled) return;
          setSources(h.sources);
          setError(null);
          refreshLib();
          return;
        } catch {
          await new Promise((r) => setTimeout(r, 500));
        }
      }
      if (!cancelled) setError("Backend not reachable. Run: collajit-server");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function withJob(start: Promise<{ job_id: string }>): Promise<JobSnap | null> {
    setBusy(true);
    setError(null);
    setNotice(null);
    setLogs([]);
    // Refresh the library grid live so fetched images appear as they download.
    const poll = window.setInterval(refreshLib, 1500);
    try {
      const { job_id } = await start;
      return await runJob(job_id, (j) => {
        setJob(j);
        if (j.logs) setLogs(j.logs);
      });
    } catch (e: any) {
      setError(e?.message || String(e));
      return null;
    } finally {
      window.clearInterval(poll);
      refreshLib();
      setBusy(false);
      setJob(null);
    }
  }

  async function addFolderFlow(path: string) {
    setLastFolder(path);
    const snap = await withJob(api.addFolder(path));
    if (snap?.result) {
      setNotice(`Added ${snap.result.processed} new image(s) from ${path}.`);
    }
  }

  async function openForPrint() {
    if (!result) return;
    const name = result.url.split("/").pop() || "collage.png";
    try {
      await api.openOutput(name);
      setNotice("Opened in your default viewer — print from there (⌘P) to pick the Pro-310.");
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }

  async function downloadResult() {
    if (!result) return;
    const name = result.url.split("/").pop() || "collage.png";
    if (IS_TAURI) {
      const dest = await saveDialog({ defaultPath: name });
      if (!dest) return;
      try {
        await api.save(name, dest);
        setNotice(`Saved to ${dest}`);
      } catch (e: any) {
        setError(e?.message || String(e));
      }
    } else {
      const a = document.createElement("a");
      a.href = asset(result.url);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
  }

  const shared = {
    lib,
    sources,
    target,
    setTarget,
    busy,
    withJob,
    refreshLib,
    setResult,
    setNotice,
    setError,
  };

  return (
    <div className="app">
      <div className="topbar">
        <div className="logo">
          colla<span>jit</span>
        </div>
        <div className="spacer" />
        <div className="status">
          {busy && job
            ? `${job.label}… ${job.total ? `${job.done}/${job.total}` : ""}`
            : `${lib.count} images in library`}
        </div>
      </div>

      <div className="body">
        <Sidebar
          lib={lib}
          refreshLib={refreshLib}
          setError={setError}
          askConfirm={askConfirm}
          askPrompt={askPrompt}
          onAddFolder={addFolderFlow}
          lastFolder={lastFolder}
        />

        <div className="main">
          <div className="workspace">
            <div className="tabs">
              {(["mosaic", "fetch", "generative"] as const).map((t) => (
                <div
                  key={t}
                  className={"tab" + (tab === t ? " active" : "")}
                  onClick={() => setTab(t)}
                >
                  {t === "mosaic" ? "Mosaic" : t === "fetch" ? "Fetch images" : "Generative"}
                </div>
              ))}
            </div>

            {error && <div className="banner bad">{error}</div>}
            {notice && <div className="banner good">{notice}</div>}
            {busy && <Progress job={job} />}

            {tab === "mosaic" && <MosaicTab {...shared} />}
            {tab === "fetch" && <FetchTab {...shared} />}
            {tab === "generative" && <GenerativeTab {...shared} />}

            <Console logs={logs} />
          </div>

          <Preview
            result={result}
            onDownload={downloadResult}
            onPrint={() => window.print()}
            onOpen={openForPrint}
          />
        </div>
      </div>

      <PrintArea result={result} />
      <DialogHost dialog={dialog} setDialog={setDialog} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
type DialogState =
  | { kind: "confirm"; message: string; resolve: (v: boolean) => void }
  | { kind: "prompt"; message: string; value: string; resolve: (v: string | null) => void };

function DialogHost({
  dialog,
  setDialog,
}: {
  dialog: DialogState | null;
  setDialog: (d: DialogState | null) => void;
}) {
  const [val, setVal] = useState("");
  useEffect(() => {
    if (dialog?.kind === "prompt") setVal(dialog.value);
  }, [dialog]);
  if (!dialog) return null;

  const cancel = () => {
    const d = dialog;
    setDialog(null);
    d.kind === "confirm" ? d.resolve(false) : d.resolve(null);
  };
  const ok = () => {
    const d = dialog;
    setDialog(null);
    d.kind === "confirm" ? d.resolve(true) : d.resolve(val);
  };

  return (
    <div className="modal-overlay" onClick={cancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-msg">{dialog.message}</div>
        {dialog.kind === "prompt" && (
          <input
            type="text"
            autoFocus
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") ok();
              if (e.key === "Escape") cancel();
            }}
          />
        )}
        <div className="modal-actions">
          <button onClick={cancel}>Cancel</button>
          <button className="primary" onClick={ok}>
            OK
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
function Sidebar(props: {
  lib: Library;
  refreshLib: () => void;
  setError: (s: string | null) => void;
  askConfirm: (m: string) => Promise<boolean>;
  askPrompt: (m: string, v?: string) => Promise<string | null>;
  onAddFolder: (path: string) => void;
  lastFolder: string;
}) {
  const { lib, askConfirm, askPrompt, refreshLib, onAddFolder, lastFolder } = props;
  const addFolder = async () => {
    // Native folder picker in the desktop app; typed-path modal in the browser.
    let path: string | null = null;
    if (IS_TAURI) {
      const sel = await openDialog({ directory: true, multiple: false, title: "Choose image folder" });
      path = typeof sel === "string" ? sel : null;
    } else {
      path = await askPrompt("Folder path to index:");
    }
    if (path) onAddFolder(path);
  };
  const clear = async () => {
    if (!(await askConfirm("Empty the library and start over?"))) return;
    await api.clear();
    refreshLib();
  };
  return (
    <div className="sidebar">
      <div className="head">
        <button onClick={addFolder}>Add folder…</button>
        <button className="ghost" onClick={clear}>
          Clear
        </button>
        <span className="count">{lib.count}</span>
      </div>
      {lastFolder && (
        <div className="hint" style={{ padding: "0 12px 8px" }} title={lastFolder}>
          Last indexed: {lastFolder}
        </div>
      )}
      {lib.count === 0 ? (
        <div className="empty">No images yet. Fetch some, or add a folder.</div>
      ) : (
        <div className="grid">
          {lib.images.map((im: LibImage) => (
            <img key={im.id} src={asset(im.thumb_url)} title={im.name} loading="lazy" />
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
function Progress({ job }: { job: JobSnap | null }) {
  const pct = job && job.total ? Math.round((job.done / job.total) * 100) : null;
  const indeterminate = pct === null;
  const label = indeterminate
    ? "Searching the web…"
    : job?.label === "fetch"
      ? "Downloading…"
      : `${job?.label || "Working"}…`;
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 8 }}>
        <b>{label}</b>
        <div className="grow" />
        <span className="status">{indeterminate ? "" : `${pct}%`}</span>
      </div>
      <div className={"progress" + (indeterminate ? " indeterminate" : "")}>
        <div style={indeterminate ? undefined : { width: `${pct}%` }} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
function TargetPicker(props: {
  target: Target;
  setTarget: (t: Target) => void;
  setError: (s: string | null) => void;
}) {
  const { target, setTarget, setError } = props;
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setTarget(await api.upload(file));
    } catch (err: any) {
      setError(err?.message || String(err));
    }
  };
  return (
    <div className="target">
      {target ? (
        <img className="thumb" src={asset(target.url)} />
      ) : (
        <div className="thumb empty">no target</div>
      )}
      <div>
        <label className="primary" style={{ display: "inline-block" }}>
          <button onClick={(e) => (e.currentTarget.nextSibling as HTMLInputElement)?.click()}>
            Choose target image…
          </button>
          <input type="file" accept="image/*" hidden onChange={onFile} />
        </label>
        <div className="hint">The picture your mosaic will recreate.</div>
      </div>
    </div>
  );
}

type Shared = {
  lib: Library;
  sources: string[];
  target: Target;
  setTarget: (t: Target) => void;
  busy: boolean;
  withJob: (p: Promise<{ job_id: string }>) => Promise<JobSnap | null>;
  refreshLib: () => void;
  setResult: (r: { url: string; info: any } | null) => void;
  setNotice: (s: string | null) => void;
  setError: (s: string | null) => void;
};

/* ------------------------------------------------------------------ */
function MosaicTab(s: Shared) {
  const [sizing, setSizing] = usePersistedState<"physical" | "grid">("m.sizing", "physical");
  const [cols, setCols] = usePersistedState("m.cols", 30); // tiles across — used in BOTH modes
  const [tilePx, setTilePx] = usePersistedState("m.tilePx", 64);
  const [wIn, setWIn] = usePersistedState("m.wIn", 7.5);
  const [hIn, setHIn] = usePersistedState("m.hIn", 7.5);
  const [dpi, setDpi] = usePersistedState("m.dpi", 300);
  const [tint, setTint] = usePersistedState("m.tint", 25);
  const [noRepeat, setNoRepeat] = usePersistedState("m.noRepeat", true);

  // Physical mode: tile size is derived from tiles-across so the user sets the
  // tile count directly (the natural control), not the tile size.
  const grid = physicalGrid(wIn, hIn, cols, dpi);
  const colsSafe = grid.cols;
  const pRows = grid.rows;
  const pTileIn = grid.tileIn;
  const pTilePx = grid.tilePx;
  const tiles = sizing === "physical" ? grid.tiles : colsSafe * colsSafe;
  const short = noRepeat ? Math.max(0, tiles - s.lib.count) : 0;

  const preset = () => {
    setSizing("physical");
    setWIn(7.5);
    setHIn(7.5);
    setCols(30);
    setDpi(300);
    setNoRepeat(true);
  };

  const generate = async () => {
    if (!s.target) return s.setError("Choose a target image first.");
    const body =
      sizing === "physical"
        ? { target_path: s.target.path, sizing, canvas_w_in: wIn, canvas_h_in: hIn, tile_in: pTileIn, dpi, tint: tint / 100, no_repeat: noRepeat }
        : { target_path: s.target.path, sizing, cols, tile_px: tilePx, tint: tint / 100, no_repeat: noRepeat };
    const snap = await s.withJob(api.mosaic(body));
    if (snap?.result) s.setResult({ url: snap.result.output_url, info: snap.result });
  };

  return (
    <>
      <div className="card">
        <h3>Target</h3>
        <TargetPicker target={s.target} setTarget={s.setTarget} setError={s.setError} />
      </div>

      <div className="card">
        <div className="row">
          <h3 style={{ margin: 0 }}>Layout</h3>
          <div className="grow" />
          <div className="preset">
            <button onClick={preset} title="7.5in canvas, 0.25in tiles, no repeats = 900 tiles">
              🐟 Eyeball-of-fish preset
            </button>
          </div>
        </div>

        <div className="row">
          <label>Sizing</label>
          <select value={sizing} onChange={(e) => setSizing(e.target.value as any)}>
            <option value="physical">Physical (inches + DPI)</option>
            <option value="grid">Grid (pixels)</option>
          </select>
        </div>

        {sizing === "physical" ? (
          <>
            <div className="row">
              <label>Canvas (in)</label>
              <input type="number" step="0.5" value={wIn} onChange={(e) => setWIn(+e.target.value)} style={{ width: 80 }} />
              <span>×</span>
              <input type="number" step="0.5" value={hIn} onChange={(e) => setHIn(+e.target.value)} style={{ width: 80 }} />
            </div>
            <div className="row">
              <label>Tiles across</label>
              <input type="number" min={1} value={cols} onChange={(e) => setCols(+e.target.value)} style={{ width: 90 }} />
              <label style={{ width: "auto" }}>DPI</label>
              <input type="number" step="50" value={dpi} onChange={(e) => setDpi(+e.target.value)} style={{ width: 80 }} />
            </div>
            <div className="statline">
              <span>Grid: <b>{colsSafe}×{pRows}</b></span>
              <span>Tiles: <b>{tiles}</b></span>
              <span>Tile: <b>{pTileIn.toFixed(2)}in / {pTilePx}px</b></span>
              <span>Output: <b>{colsSafe * pTilePx}×{pRows * pTilePx}px</b></span>
            </div>
          </>
        ) : (
          <>
            <div className="row">
              <label>Tiles across</label>
              <input type="number" min={1} value={cols} onChange={(e) => setCols(+e.target.value)} style={{ width: 90 }} />
            </div>
            <div className="row">
              <label>Tile px</label>
              <input type="number" value={tilePx} onChange={(e) => setTilePx(+e.target.value)} style={{ width: 90 }} />
            </div>
          </>
        )}

        <div className="row">
          <label>Colour tint</label>
          <input type="range" min={0} max={100} value={tint} onChange={(e) => setTint(+e.target.value)} />
          <span style={{ width: 36 }}>{tint}%</span>
        </div>
        <div className="row">
          <label>No repeats</label>
          <input type="checkbox" checked={noRepeat} onChange={(e) => setNoRepeat(e.target.checked)} />
          <span className="hint" style={{ margin: 0 }}>each source image used at most once</span>
        </div>

        {short > 0 && (
          <div className="banner warn">
            No-repeat needs <b>{tiles}</b> unique images; library has <b>{s.lib.count}</b>.
            Fetch ~{short} more (try the Fetch tab with this target) or tiles will repeat.
          </div>
        )}

        <button className="primary" disabled={s.busy || !s.target} onClick={generate}>
          Generate mosaic
        </button>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
function FetchTab(s: Shared) {
  const [terms, setTerms] = usePersistedState("f.terms", "");
  const [count, setCount] = usePersistedState("f.count", 300);
  const [minRes, setMinRes] = usePersistedState("f.minRes", 400);
  const [picked, setPicked] = usePersistedState<Record<string, boolean>>("f.sources", {});
  const [destDir, setDestDir] = usePersistedState("f.destDir", "");
  const [suggesting, setSuggesting] = useState(false);

  const enabled = s.sources.filter((id) => picked[id] !== false);

  const pickDest = async () => {
    if (IS_TAURI) {
      const sel = await openDialog({ directory: true, multiple: false, title: "Save fetched images to" });
      if (typeof sel === "string") setDestDir(sel);
    } else {
      const p = window.prompt("Folder to save fetched images to (blank = managed cache):", destDir);
      if (p !== null) setDestDir(p);
    }
  };

  const suggest = async () => {
    if (!s.target) return s.setError("Choose a target image to suggest from.");
    setSuggesting(true);
    s.setError(null);
    try {
      const { terms: t } = await api.suggest(s.target.path);
      setTerms(t.join(", "));
    } catch (e: any) {
      s.setError(e?.message || String(e));
    } finally {
      setSuggesting(false);
    }
  };

  const doFetch = async () => {
    const list = terms.split(",").map((t) => t.trim()).filter(Boolean);
    if (!list.length) return s.setError("Type what to fetch, or use Suggest.");
    const snap = await s.withJob(
      api.fetch({
        terms: list,
        target_path: s.target?.path ?? null,
        count,
        min_resolution: minRes,
        sources: enabled,
        dest_dir: destDir || null,
      })
    );
    if (snap?.result) {
      s.refreshLib();
      const r = snap.result;
      if (r.downloaded > 0) {
        s.setNotice(`Added ${r.downloaded} new image(s). Library now has ${r.catalog_total}.`);
      } else {
        const counts = r.source_counts || {};
        const breakdown = Object.entries(counts)
          .map(([k, v]) => `${k}: ${v}`)
          .join(", ");
        const rateLimited = (r.errors || []).length > 0;
        s.setNotice(
          rateLimited
            ? `No images — a source is rate-limited (${(r.errors || []).join("; ")}). Enable Wikimedia/The Met and retry; Openverse recovers later. [${breakdown}]`
            : `No new images (${breakdown}). Try different/more specific terms, add a target for colour variety, or enable more sources. Library: ${r.catalog_total}.`
        );
      }
    }
  };

  return (
    <>
      <div className="card">
        <h3>Target (optional — drives colour matching & suggestions)</h3>
        <TargetPicker target={s.target} setTarget={s.setTarget} setError={s.setError} />
      </div>

      <div className="card">
        <h3>What to fetch</h3>
        <div className="row">
          <input
            type="text"
            placeholder="e.g. fish, tropical fish, koi"
            value={terms}
            onChange={(e) => setTerms(e.target.value)}
          />
        </div>
        <div className="row">
          <button onClick={suggest} disabled={suggesting || !s.target}>
            {suggesting ? "Asking Claude…" : "Suggest from image (Claude)"}
          </button>
          <span className="hint" style={{ margin: 0 }}>
            fills the box — edit freely, or just type your own
          </span>
        </div>
        <div className="row">
          <label>Images</label>
          <input type="number" value={count} onChange={(e) => setCount(+e.target.value)} style={{ width: 90 }} />
          <label style={{ width: "auto" }}>Min resolution</label>
          <input type="number" step={50} value={minRes} onChange={(e) => setMinRes(+e.target.value)} style={{ width: 90 }} />
        </div>
        <div className="row">
          <label>Sources</label>
          <div className="checks">
            {s.sources.map((id) => (
              <label key={id}>
                <input
                  type="checkbox"
                  checked={picked[id] !== false}
                  onChange={(e) => setPicked({ ...picked, [id]: e.target.checked })}
                />
                {id}
              </label>
            ))}
          </div>
        </div>
        <div className="row">
          <label>Save to</label>
          <button onClick={pickDest}>{destDir ? "Change folder…" : "Choose folder…"}</button>
          {destDir ? (
            <button className="ghost" onClick={() => setDestDir("")} title="Use the managed cache">
              ✕
            </button>
          ) : null}
          <span className="hint" style={{ margin: 0, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={destDir}>
            {destDir || "managed cache (~/.collajit/fetched)"}
          </span>
        </div>
        <button className="primary" disabled={s.busy} onClick={doFetch}>
          Fetch &amp; add to library
        </button>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
function GenerativeTab(s: Shared) {
  const [mode, setMode] = usePersistedState<"color_sort" | "embedding">("g.mode", "color_sort");
  const [key, setKey] = usePersistedState("g.key", "hue");
  const [method, setMethod] = usePersistedState("g.method", "pca");
  const [cols, setCols] = usePersistedState("g.cols", 40);
  const [tilePx, setTilePx] = usePersistedState("g.tilePx", 64);

  const generate = async () => {
    const snap = await s.withJob(api.generative({ mode, key, method, cols, tile_px: tilePx }));
    if (snap?.result) s.setResult({ url: snap.result.output_url, info: snap.result });
  };

  return (
    <div className="card">
      <h3>Generative layout</h3>
      <div className="row">
        <label>Mode</label>
        <select value={mode} onChange={(e) => setMode(e.target.value as any)}>
          <option value="color_sort">Colour sort</option>
          <option value="embedding">Embedding (similarity)</option>
        </select>
      </div>
      {mode === "color_sort" ? (
        <div className="row">
          <label>Order by</label>
          <select value={key} onChange={(e) => setKey(e.target.value)}>
            <option value="hue">hue</option>
            <option value="brightness">brightness</option>
            <option value="darkness">darkness</option>
          </select>
        </div>
      ) : (
        <div className="row">
          <label>Method</label>
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="pca">PCA (fast)</option>
            <option value="tsne">t-SNE (slower)</option>
          </select>
        </div>
      )}
      <div className="row">
        <label>Columns</label>
        <input type="number" value={cols} onChange={(e) => setCols(+e.target.value)} style={{ width: 90 }} />
        <label style={{ width: "auto" }}>Tile px</label>
        <input type="number" value={tilePx} onChange={(e) => setTilePx(+e.target.value)} style={{ width: 90 }} />
      </div>
      <button className="primary" disabled={s.busy || s.lib.count === 0} onClick={generate}>
        Generate layout
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
function Console({ logs }: { logs: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [logs]);
  if (logs.length === 0) return null;
  return (
    <div className="card console-card">
      <h3>Console</h3>
      <div className="console" ref={ref}>
        {logs.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
function PrintArea({ result }: { result: { url: string; info: any } | null }) {
  if (!result) return null;
  const w = result.info?.inches_w;
  const style: React.CSSProperties = w
    ? { width: `${w}in`, height: "auto" }
    : { maxWidth: "100%", maxHeight: "100%" };
  return (
    <div className="print-root">
      <img src={asset(result.url)} style={style} />
    </div>
  );
}

function Preview({
  result,
  onDownload,
  onPrint,
  onOpen,
}: {
  result: { url: string; info: any } | null;
  onDownload: () => void;
  onPrint: () => void;
  onOpen: () => void;
}) {
  const [scale, setScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);

  // Reset view when a new artwork loads.
  useEffect(() => {
    setScale(1);
    setTx(0);
    setTy(0);
  }, [result?.url]);

  const fit = () => {
    setScale(1);
    setTx(0);
    setTy(0);
  };
  const onWheel = (e: React.WheelEvent) => {
    if (!result) return;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    setScale((s) => Math.min(20, Math.max(0.1, s * factor)));
  };
  const onMouseDown = (e: React.MouseEvent) => {
    if (!result) return;
    drag.current = { x: e.clientX, y: e.clientY, tx, ty };
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!drag.current) return;
    setTx(drag.current.tx + (e.clientX - drag.current.x));
    setTy(drag.current.ty + (e.clientY - drag.current.y));
  };
  const endDrag = () => {
    drag.current = null;
  };

  return (
    <div className="preview">
      <div className="row" style={{ margin: 0 }}>
        <h3 style={{ margin: 0 }}>Preview</h3>
        <div className="grow" />
        {result && (
          <>
            <button onClick={() => setScale((s) => Math.max(0.1, s / 1.15))}>−</button>
            <button onClick={() => setScale((s) => Math.min(20, s * 1.15))}>+</button>
            <button onClick={fit}>Fit</button>
            <button onClick={onOpen} title="Open the full-resolution file to print via your printer driver">
              Open
            </button>
            <button onClick={onPrint}>Print…</button>
            <button className="primary" onClick={onDownload}>
              Download
            </button>
          </>
        )}
      </div>
      <div
        className="canvaswrap"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
        style={{ cursor: result ? (drag.current ? "grabbing" : "grab") : "default" }}
      >
        {result ? (
          <img
            src={asset(result.url)}
            draggable={false}
            style={{ transform: `translate(${tx}px, ${ty}px) scale(${scale})` }}
          />
        ) : (
          <div className="placeholder">Your generated artwork appears here.</div>
        )}
      </div>
      <div className="statline">
        {result?.info?.width && (
          <span>
            Size: <b>{result.info.width}×{result.info.height}px</b>
          </span>
        )}
        {result?.info?.tiles ? <span>Tiles: <b>{result.info.tiles}</b></span> : null}
        {result?.info?.short_by ? (
          <span style={{ color: "var(--warn)" }}>Repeated {result.info.short_by} tiles</span>
        ) : null}
        {result && <span>Wheel = zoom · drag = pan</span>}
      </div>
    </div>
  );
}
