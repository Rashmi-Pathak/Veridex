# Veridex browser extension

Right-click any image on the web and recover its stripped C2PA provenance through Veridex's live
Soft Binding Resolution API. A Manifest V3 extension, no build step, no bundler.

## What it does

1. You right-click an image and choose **Recover provenance with Veridex**.
2. The extension fetches the image bytes and POSTs them to the public SBR endpoint
   `POST /matches/byContent` on the live Veridex API.
3. On a match it pulls the recovered manifest (`GET /manifests/{id}`) and renders a provenance card
   on the page: the manifest id, the match similarity, and the system provenance (model, provider,
   generator).
4. If the image is not in this Veridex instance's registry it says so honestly. A single instance
   only recovers media it has ingested (the SBR spec's goal is federated, cross-repository lookup).

This turns Veridex from a demo site into a tool you can point at any image anywhere.

## Load it (unpacked, ~30 seconds)

Chrome or Edge:

1. Open `chrome://extensions` (or `edge://extensions`).
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and select this `extension/` folder.
4. The Veridex icon appears in the toolbar. Click it to confirm `API online`.

## Try it

The live registry contains Veridex's generated and seeded assets. The easiest demo:

1. Open the live app: <YOUR_VERIDEX_SITE_URL>.
2. Right-click one of the demo or provider images on that page and choose
   **Recover provenance with Veridex**. You will see a green **RECOVERED** card with the model and
   provider.
3. Right-click any random image elsewhere on the web. You will get the honest
   **No provenance found in this Veridex registry** card.

You can also generate a fresh image in the app (the Generate panel), then right-click it and recover
it: a brand new asset, recovered from its bytes.

## How it talks to the backend

- API base: `YOUR_VERIDEX_API_URL` (the live deploy).
- Endpoints used: `POST /matches/byContent`, `GET /manifests/{id}`, `GET /health` (popup status).
- No credentials. The recovery API is public and read-only. The extension never uploads anything
  except the image you explicitly right-click.

## Permissions

- `contextMenus`: the right-click menu item on images.
- `scripting`: to render the result card on the current page.
- `host_permissions: <all_urls>`: so it can fetch the bytes of whatever image you right-click and
  reach the Veridex API. The card is built with `createElement` + `textContent` only (no `innerHTML`),
  so it cannot inject HTML into the host page.
