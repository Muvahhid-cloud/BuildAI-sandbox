# Viewer screenshots — V7 bay-aware rooms (step 1)

Headless Chromium (SwiftShader software WebGL), 1600×1000 window, canvas only. Front and Rear
camera presets; the side view is the east facade, framed like the Front preset (dev-only
`setPose`, camera at +x). "Before" = `main` (layout@1.14.0); "after" = `v7-bay-aware-rooms`
(layout@1.15.0). Both sets were generated through the real product path
(`POST /api/v1/projects/{id}/generate` with the reference specs in `data/fixtures/specs`); the
stored versions record the engine versions.

| House | View | Before (layout@1.14.0) | After (layout@1.15.0) |
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

What to look for: bathroom/WC windows at the facade's main width, at their privacy sill (04 and
08 east, upper left; 01 and 05); the stair-void window that shared a bay with a bedroom or stair
window is gone (05 and 08 front); 04's upper corridor window stands over the hall window (west
facade, not in these views; covered by tests). Rooms are unchanged (step 2 not adopted, see
`docs/3d-engine.md` §16.17).
