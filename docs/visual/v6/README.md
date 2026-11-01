# Viewer screenshots — V6 window consistency

Headless Chromium (SwiftShader software WebGL), 1600×1000 window, canvas only. Front and Rear
camera presets; the side view is the east facade, framed like the Front preset (dev-only
`setPose`, camera at +x). "Before" = `main` (layout@1.11.0); "after" = `v6-window-consistency`
(layout@1.14.0). Both sets were generated through the real product path
(`POST /api/v1/projects/{id}/generate` with the reference specs in `data/fixtures/specs`); the
stored versions record the engine versions.

| House | View | Before (layout@1.11.0) | After (layout@1.14.0) |
|---|---|---|---|
| 01 family house 280 m² | front | ![](before-01-front.jpg) | ![](after-01-front.jpg) |
| 01 | rear | ![](before-01-rear.jpg) | ![](after-01-rear.jpg) |
| 01 | side (east) | ![](before-01-side.jpg) | ![](after-01-side.jpg) |
| 04 narrow-plot townhouse | front | ![](before-04-front.jpg) | ![](after-04-front.jpg) |
| 04 | rear | ![](before-04-rear.jpg) | ![](after-04-rear.jpg) |
| 04 | side (east) | ![](before-04-side.jpg) | ![](after-04-side.jpg) |
| 05 three-storey villa 360 m² | front | ![](before-05-front.jpg) | ![](after-05-front.jpg) |
| 05 | rear | ![](before-05-rear.jpg) | ![](after-05-rear.jpg) |
| 05 | side (east) | ![](before-05-side.jpg) | ![](after-05-side.jpg) |
| 08 classic brick 220 m² | front | ![](before-08-front.jpg) | ![](after-08-front.jpg) |
| 08 | rear | ![](before-08-rear.jpg) | ![](after-08-rear.jpg) |
| 08 | side (east) | ![](before-08-side.jpg) | ![](after-08-side.jpg) |

What to look for: 08 east — the narrow windows beside the wider ones are gone (one window per
bay on both storeys) and the small bathroom window's head now lines up with the others; every
storey has one window head line (stair, hall and service windows raised to it, 01, 04, 05);
fewer window widths on the front and rear facades. Numbers: `docs/3d-engine.md` §16.16.
