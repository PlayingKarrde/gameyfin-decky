// Adds a "Gameyfin" submenu (Update, Refresh artwork, Uninstall) to the Steam library context menu of games
// the plugin installed. Steam's own "Remove non-Steam game" only deletes the shortcut.
// One submenu rather than loose items keeps Steam's menu from growing with every feature.
//
// Steam's menu internals are undocumented; this follows decky-steamgriddb's
// contextMenuPatch (checked against the Nov 2026 client). Every step is guarded:
// if Steam changes shape, the menu simply goes without our items.
import {
  Export,
  MenuGroup,
  MenuItem,
  Patch,
  afterPatch,
  fakeRenderComponent,
  findInReactTree,
  findInTree,
  findModuleByExport,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, ReactElement } from "react";
import { applyGameArtwork, getSnapshot, healthOf, statusFor } from "./installs";
import { confirmUninstall, confirmUpdate } from "./components/InstallModals";

const KEY_PREFIX = "gameyfin-";

function findLibraryContextMenu(): any | null {
  try {
    const mod = findModuleByExport((e: Export) => e?.toString && e.toString().includes("().LibraryContextMenu"));
    if (!mod) return null;
    const sibling = Object.values(mod).find((s: any) => s?.toString?.().includes("navigator:")) as FC | undefined;
    return sibling ? fakeRenderComponent(sibling).type : null;
  } catch (e) {
    console.warn("[gameyfin] context menu lookup failed", e);
    return null;
  }
}

/** Our submenu for this appid, or [] if it isn't a Gameyfin install (or nothing applies). */
function itemsFor(appid: number): ReactElement[] {
  const snap = getSnapshot();
  const inst = snap.installed.find((g) => g.appid === appid);
  if (!inst) return [];
  const st = statusFor(snap, inst.game_id);
  const busy = snap.jobs.some((j) => String(j.game_id) === inst.game_id && j.phase !== "error" && j.phase !== "cancelled");
  if (busy) return [];
  const items: ReactElement[] = [];
  if (st?.update_available && healthOf(inst, st) === "ok") {
    items.push(
      <MenuItem key="update" onSelected={() => void confirmUpdate(inst, st)}>
        Update…
      </MenuItem>,
    );
  }
  items.push(
    <MenuItem
      key="artwork"
      onSelected={() =>
        void applyGameArtwork(inst.game_id, appid).then((ok) =>
          toaster.toast({
            title: "Gameyfin",
            body: ok ? `Artwork refreshed for ${inst.title}` : `Couldn't load artwork for ${inst.title}`,
          }),
        )
      }
    >
      Refresh artwork
    </MenuItem>,
  );
  items.push(
    <MenuItem key="uninstall" onSelected={() => void confirmUninstall(inst)}>
      Uninstall…
    </MenuItem>,
  );
  return [
    <MenuGroup key={`${KEY_PREFIX}menu`} label="Gameyfin">
      {items}
    </MenuGroup>,
  ];
}

/** Insert before "Properties…", like decky-steamgriddb, after removing stale copies. */
function splice(children: any[], appid: number) {
  for (let i = children.length - 1; i >= 0; i--) {
    if (typeof children[i]?.key === "string" && children[i].key.startsWith(KEY_PREFIX)) children.splice(i, 1);
  }
  const items = itemsFor(appid);
  if (!items.length) return;
  const at = children.findIndex((item) =>
    findInReactTree(item, (x: any) => x?.onSelected && x.onSelected.toString().includes("AppProperties")),
  );
  // Only the top-level menu has "Properties…". The "Manage ›" submenu is rendered by the
  // same component and passes isAppMenu, so without this guard it got a second copy.
  if (at < 0) return;
  children.splice(at, 0, ...items);
}

/** The app menu, not the screenshot/collection menus that share the component. */
const isAppMenu = (items: any[]) =>
  !!items?.length &&
  !!findInReactTree(items, (x: any) => x?.props?.onSelected && x.props.onSelected.toString().includes("launchSource"));

function appidOf(menuItems: any[], fallback: number): number {
  const owner = menuItems.find((x: any) => x?._owner?.pendingProps?.overview?.appid);
  if (owner) return owner._owner.pendingProps.overview.appid;
  const found = findInTree(menuItems, (x: any) => x?.app?.appid, { walkable: ["props", "children"] });
  return found?.app?.appid ?? fallback;
}

export function patchContextMenu(): () => void {
  const Menu = findLibraryContextMenu();
  if (!Menu?.prototype?.render) {
    console.warn("[gameyfin] LibraryContextMenu not found; context menu items disabled");
    return () => undefined;
  }
  const patches: Patch[] = [];
  let innerPatched = false;
  let protoPatched = false;

  patches.push(
    afterPatch(Menu.prototype, "render", (_: unknown[], component: any) => {
      try {
        let appid = 0;
        if (component._owner) appid = component._owner.pendingProps?.overview?.appid ?? 0;
        else {
          const found = findInTree(component.props?.children, (x: any) => x?.app?.appid, {
            walkable: ["props", "children"],
          });
          appid = found?.app?.appid ?? 0;
        }
        if (innerPatched) {
          // Later menus: the prototype patches below do the work; this covers the outer children too.
          const kids = component.props?.children;
          if (Array.isArray(kids) && isAppMenu(kids)) splice(kids, appid);
          return component;
        }
        innerPatched = true;
        patches.push(
          afterPatch(component, "type", (_: unknown[], ret: any) => {
            if (protoPatched || !ret?.type?.prototype) return ret;
            protoPatched = true;
            patches.push(
              afterPatch(ret.type.prototype, "render", (_: unknown[], ret2: any) => {
                try {
                  const menuItems = ret2.props.children[0];
                  if (isAppMenu(menuItems)) splice(menuItems, appidOf(menuItems, appid));
                } catch (e) {
                  console.warn("[gameyfin] context menu render patch", e);
                }
                return ret2;
              }),
            );
            patches.push(
              afterPatch(ret.type.prototype, "shouldComponentUpdate", ([nextProps]: any[], should: any) => {
                try {
                  if (should === true && isAppMenu(nextProps.children))
                    splice(nextProps.children, appidOf(nextProps.children, appid));
                } catch (e) {
                  console.warn("[gameyfin] context menu update patch", e);
                }
                return should;
              }),
            );
            return ret;
          }),
        );
      } catch (e) {
        console.warn("[gameyfin] context menu patch", e);
      }
      return component;
    }),
  );

  return () => patches.forEach((p) => p.unpatch());
}
