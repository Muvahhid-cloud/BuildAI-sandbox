# Web app redesign — before / after

Headless Chromium (SwiftShader software WebGL). "Before" = `main` (c2967ce); "after" =
`ui-redesign`. Same account and data in both sets: projects generated through the product path
from the reference specs. 1440×900 unless noted. The round "N" badge in the lower left is the
Next.js dev-server indicator (not part of the product).

The generation screen shows a real generation started from the prompt box; its status response
is held at the backend stage `layout` (request interception in the screenshot script only), so
the stage names and their order are the product's own.

| Screen | Before | After |
|---|---|---|
| Projects / landing | ![](before-landing.jpg) | ![](after-landing.jpg) |
| Generation (real stages) | ![](before-generation.jpg) | ![](after-generation.jpg) |
| Editor, 3D | ![](before-editor-3d.jpg) | ![](after-editor-3d.jpg) |
| Editor, floor plan | ![](before-plan.jpg) | ![](after-plan.jpg) |
| Modify with AI drawer | ![](before-modify-drawer.jpg) | ![](after-modify-drawer.jpg) |
| Dark: landing | ![](before-dark-landing.jpg) | ![](after-dark-landing.jpg) |
| Dark: editor | ![](before-dark-editor.jpg) | ![](after-dark-editor.jpg) |
| 375 px: sign in | ![](before-mobile-login.jpg) | ![](after-mobile-login.jpg) |
| 375 px: landing | ![](before-mobile-landing.jpg) | ![](after-mobile-landing.jpg) |

"Before" dark mode is the OS setting (there was no toggle); the old dark styles were partial.

After only:

| Screen | |
|---|---|
| Inspector (room selected) | ![](after-inspector.jpg) |
| Compare drawer | ![](after-compare-drawer.jpg) |
| History drawer | ![](after-history-drawer.jpg) |
| Report drawer | ![](after-report-drawer.jpg) |
| New design drawer (AI) | ![](after-new-design-drawer.jpg) |
| Specification form | ![](after-spec-form.jpg) |
| Dark: floor plan (paper stays white) | ![](after-dark-plan.jpg) |
| Dark: Modify with AI | ![](after-dark-modify-drawer.jpg) |
| Sign in (1024 px) | ![](after-login.jpg) |
| Editor at 1024×768 | ![](after-editor-1024.jpg) |
