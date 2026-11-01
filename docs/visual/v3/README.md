# Viewer screenshots — V3 architectural design quality

Headless Chromium (SwiftShader software WebGL), 1600×1000 window, canvas only, Exterior and Rear
camera presets. "Before" = `main` (layout@1.7.0, engine@3); "after" = `v3-architecture`
(layout@1.8.0, engine@4). Generated houses were created through the real product path
(`POST /api/v1/projects/{id}/generate` with the reference specs in `data/fixtures/specs`).

| House | Before | After |
|---|---|---|
| 01 family house 280 m², modern, flat roof, render | ![](before-01-exterior.jpg) | ![](after-01-exterior.jpg) |
| 01 rear | ![](before-01-rear.jpg) | ![](after-01-rear.jpg) |
| 02 compact bungalow, Scandinavian, gable, timber | ![](before-02-exterior.jpg) | ![](after-02-exterior.jpg) |
| 02 rear (gable end) | ![](before-02-rear.jpg) | ![](after-02-rear.jpg) |
| 04 narrow-plot townhouse, traditional, gable, brick | ![](before-04-exterior.jpg) | ![](after-04-exterior.jpg) |
| 04 rear | ![](before-04-rear.jpg) | ![](after-04-rear.jpg) |
| 08 classic brick, hip | ![](before-08-exterior.jpg) | ![](after-08-exterior.jpg) |
| 08 rear | ![](before-08-rear.jpg) | ![](after-08-rear.jpg) |
| 11 L-shaped bungalow, contemporary, hip | ![](before-11-exterior.jpg) | ![](after-11-exterior.jpg) |
| 11 rear | ![](before-11-rear.jpg) | ![](after-11-rear.jpg) |
| Demo house (hand-authored fixture) | ![](before-demo-exterior.jpg) | ![](after-demo-exterior.jpg) |

What to look for: closed gable ends (02, 04), roof fascia/soffit trim (all), gravel flat roofs
with facade parapets and coping (01, garages of 08 and 11), timber accent cladding on the garage
(01, 11), timber facades as boards (02), the entrance canopy (every generated house), upper
windows standing on the axes of the windows below where they fit (04 front).

The demo house is a hand-authored fixture: its content is unchanged (it already has a brick
ground floor and render above, and no canopy is added to it); V3 shows there as roof trim only.
