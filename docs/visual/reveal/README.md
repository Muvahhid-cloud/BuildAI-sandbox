# Build reveal — screenshots

Headless Chromium (SwiftShader software WebGL), 1440×900, `generation-reveal`. A real AI
generation started from the prompt box (offline mock interpreter). The round "N" badge is the
Next.js dev-server indicator.

The waiting frames hold the generation's status response at a real backend stage (request
interception in the screenshot script only: the mock finishes too fast to capture). The assembly
frames are the real effect paused at a fixed time with the dev-only
`window.__buildaiReveal.freeze(t)`.

| Phase | |
|---|---|
| Waiting — stage "Understanding your requirements" | ![](waiting-1-interpreting.jpg) |
| Waiting — the stage just changed to "Generating the layout" (burst, denser) | ![](waiting-2-layout-burst.jpg) |
| Waiting — "Generating the layout", settled | ![](waiting-3-layout.jpg) |
| Assembly at 0.5 s — the cloud over the dark veil, first particles leaving | ![](assembly-0.5s.jpg) |
| Assembly at 1.5 s — the lower storey has landed, the sweep starts | ![](assembly-1.5s.jpg) |
| Assembly at 2.4 s — meshes revealed up to the sweep sheet, upper particles above it | ![](assembly-2.4s.jpg) |
| Assembly at 3.0 s — veil lifted, the last particles fade on the roof | ![](assembly-3.0s.jpg) |
| Finished (after skip / end) with the generation summary | ![](finished.jpg) |
| After "Apply" in Modify with AI — changed elements sparkle | ![](sparkle.jpg) |
| Toolbar with a drawer open — re-centred in the visible canvas, wrapped | ![](toolbar-with-drawer.jpg) |
