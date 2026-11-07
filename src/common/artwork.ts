// Steam custom artwork for a shortcut. Synced from decky-common; edit it there.
//
// Backend contract (the plugin's src/backend.ts must export these):
//   getArtwork(url)       -> Result<{ content_type, size, chunks }>   full-size original, cached on disk
//   getImageChunk(url, i) -> Result<string>                            base64 slice i of that original
//   dropArtwork(url)      -> Result<null>                              free the original once Steam has it
import { dropArtwork, getArtwork, getImageChunk } from "../backend";

/** One image URL per Steam artwork slot. URLs are whatever the plugin's getArtwork accepts. */
export type ArtPlan = { capsule: string | null; wide: string | null; hero: string | null; logo: string | null };

const ASSET = { capsule: 0, hero: 1, logo: 2, header: 3, icon: 4 } as const;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function fetchOriginal(url: string): Promise<string | null> {
  const info = await getArtwork(url);
  if (!info.ok) return null;
  const parts: string[] = [];
  for (let i = 0; i < info.data.chunks; i++) {
    const c = await getImageChunk(url, i);
    if (!c.ok) return null;
    parts.push(c.data);
  }
  return `data:${info.data.content_type};base64,${parts.join("")}`;
}

/** Re-encode via canvas so Steam always gets PNG (covers webp etc.). Returns bare base64. */
async function toPngBase64(dataUrl: string): Promise<string> {
  if (dataUrl.startsWith("data:image/png;")) return dataUrl.slice(dataUrl.indexOf(",") + 1);
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const i = new Image();
    i.onload = () => resolve(i);
    i.onerror = () => reject(new Error("decode failed"));
    i.src = dataUrl;
  });
  const c = document.createElement("canvas");
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  c.getContext("2d")!.drawImage(img, 0, 0);
  const out = c.toDataURL("image/png");
  return out.slice(out.indexOf(",") + 1);
}

async function setArt(appId: number, url: string, types: number[]): Promise<boolean> {
  const src = await fetchOriginal(url);
  if (!src) return false;
  const b64 = await toPngBase64(src);
  for (const t of types) {
    await SteamClient.Apps.ClearCustomArtworkForApp(appId, t as any).catch(() => undefined);
    await sleep(300); // Clear resolves before it's actually cleared
    await SteamClient.Apps.SetCustomArtworkForApp(appId, b64, "png", t as any);
  }
  return true;
}

// A new shortcut's logo isn't drawn (Steam shows the title as text) until a logo position
// exists in grid/<appid>.json. This is Steam's own default, as its "Adjust logo" UI saves it.
const DEFAULT_LOGO_POSITION = { nVersion: 1, logoPosition: { pinnedPosition: "BottomLeft", nWidthPct: 50, nHeightPct: 50 } };

/** Best effort: failures are logged, never thrown. Slots without a URL are left alone.
 *  Returns true if at least one image was set. */
export async function applyArtwork(appId: number, plan: Partial<ArtPlan>): Promise<boolean> {
  // Group by URL so an image used for two slots (e.g. the same header) is fetched once.
  const byUrl = new Map<string, number[]>();
  const slots: [string | null | undefined, number][] = [
    [plan.capsule, ASSET.capsule],
    [plan.wide, ASSET.header],
    [plan.hero, ASSET.hero],
    [plan.logo, ASSET.logo],
  ];
  for (const [url, t] of slots) if (url) byUrl.set(url, [...(byUrl.get(url) ?? []), t]);
  let any = false;
  for (const [url, types] of byUrl) {
    try {
      const ok = await setArt(appId, url, types);
      any ||= ok;
      if (ok && types.includes(ASSET.logo)) {
        await SteamClient.Apps.SetCustomLogoPositionForApp(appId, JSON.stringify(DEFAULT_LOGO_POSITION));
      }
    } catch (e) {
      console.warn("[artwork] failed", url, e);
    }
    void dropArtwork(url).catch(() => undefined);
  }
  return any;
}
