# Third-party notices

The repository license applies to project-authored code. Third-party code keeps
its original copyright notices and licenses; it is not relicensed by this project.

## noVNC 1.6.0

- Source: https://github.com/novnc/noVNC/tree/v1.6.0
- npm package: `@novnc/novnc@1.6.0`, bundled under `vendor/package/`.
- Core library license: Mozilla Public License 2.0.
- Authors and full license information: `vendor/package/AUTHORS`,
  `vendor/package/LICENSE.txt`, and `vendor/package/docs/LICENSE.*`.
- The unmodified npm source is included alongside the reproducible
  `build_frontend.cjs` adaptation. During bundling only, one H.264 feature probe
  in `lib/util/browser.js` is set to false to remove incompatible top-level await.
- The resulting library code is included in `frontend.js`.

## pako

The noVNC package includes pako under `vendor/package/lib/vendor/pako/`.
Its MIT license is preserved at `vendor/package/lib/vendor/pako/LICENSE`, copied
from the matching noVNC v1.6.0 source distribution.

## Installed dependencies

Python dependencies in `requirements.txt`, the esbuild development dependency,
and system packages such as x11vnc/Xorg are installed separately. They are not
vendored as executable binaries here and retain their upstream licenses.
