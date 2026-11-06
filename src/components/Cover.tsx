import { CSSProperties, useEffect, useRef, useState } from "react";
import { getImage, getImageChunk, saveThumbnail } from "../backend";

const THUMB_WIDTH = 300;

// Session-wide cache of image url -> data URL (null = unavailable).
const cache = new Map<string, Promise<string | null>>();

// Cap concurrent bridge calls so a big grid doesn't flood the backend.
const MAX_CONCURRENT = 4;
let active = 0;
const queue: (() => void)[] = [];

function schedule<T>(fn: () => Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const run = () => {
      active++;
      fn()
        .then(resolve, reject)
        .finally(() => {
          active--;
          queue.shift()?.();
        });
    };
    if (active < MAX_CONCURRENT) run();
    else queue.push(run);
  });
}

function decode(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("decode failed"));
    img.src = src;
  });
}

/** Downscale to a small JPEG so the grid stays light and the disk cache is cheap. */
async function toThumbnail(src: string): Promise<string> {
  const img = await decode(src);
  const scale = Math.min(1, THUMB_WIDTH / img.naturalWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(img.naturalWidth * scale);
  canvas.height = Math.round(img.naturalHeight * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no canvas");
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85);
}

async function fetchThumb(url: string): Promise<string | null> {
  const info = await getImage(url);
  if (!info.ok) return null;
  if ("thumb" in info.data) return info.data.thumb;

  // Not cached yet: pull the original in bridge-sized chunks, then downscale.
  const parts: string[] = [];
  for (let i = 0; i < info.data.chunks; i++) {
    const c = await getImageChunk(url, i);
    if (!c.ok) return null;
    parts.push(c.data);
  }
  const thumb = await toThumbnail(`data:${info.data.content_type};base64,${parts.join("")}`);
  saveThumbnail(url, thumb).catch(() => undefined); // best effort
  return thumb;
}

export function loadImage(url: string): Promise<string | null> {
  let p = cache.get(url);
  if (!p) {
    p = schedule(() => fetchThumb(url)).catch(() => null);
    cache.set(url, p);
  }
  return p;
}

type Props = { url: string | null; title: string; style?: CSSProperties };

/** Portrait cover that only fetches once scrolled near the viewport. */
export function Cover({ url, title, style }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !url) return;
    let alive = true;
    loadImage(url).then((s) => alive && setSrc(s));
    return () => {
      alive = false;
    };
  }, [visible, url]);

  return (
    <div
      ref={ref}
      style={{
        aspectRatio: "2 / 3",
        width: "100%",
        borderRadius: "4px",
        overflow: "hidden",
        background: "linear-gradient(160deg, #2a3442, #161b22)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        ...style,
      }}
    >
      {src ? (
        <img src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      ) : (
        <div style={{ padding: "8px", textAlign: "center", fontSize: "13px", color: "#8b929a" }}>{title}</div>
      )}
    </div>
  );
}
