#!/usr/bin/env node
'use strict';

// Reproducible browser build for both Xorg and the synthetic fixture.
// noVNC 1.6.0's npm CommonJS artifact contains a top-level await in its H.264
// feature probe. The x11vnc/fixture backends do not use H.264. Disable that probe
// at build time without changing any vendored package files.
const esbuild = require('esbuild');
const fs = require('node:fs');
const path = require('node:path');

const root = __dirname;
const browserSource = path.join(root, 'vendor/package/lib/util/browser.js');
const needle = 'exports.supportsWebCodecsH264Decode = supportsWebCodecsH264Decode = await _checkWebCodecsH264DecodeSupport();';

esbuild.build({
  absWorkingDir: root,
  entryPoints: ['client.js'],
  bundle: true,
  platform: 'browser',
  format: 'iife',
  outfile: 'frontend.js',
  banner: {
    js: '// Remote console / noVNC 1.6.0. H.264 feature detection disabled for CommonJS compatibility; other encodings remain available.',
  },
  plugins: [{
    name: 'raw-only-novnc-commonjs',
    setup(build) {
      build.onLoad({ filter: /vendor\/package\/lib\/util\/browser\.js$/ }, args => {
        if (path.resolve(args.path) !== browserSource) {
          throw new Error('Unexpected source path; refusing build adaptation');
        }
        const original = fs.readFileSync(args.path, 'utf8');
        if (original.split(needle).length !== 2) {
          throw new Error('Unexpected noVNC package source; refusing unverified adaptation');
        }
        return {
          contents: original.replace(needle, 'exports.supportsWebCodecsH264Decode = supportsWebCodecsH264Decode = false; // Raw-only fixture build adaptation.'),
          loader: 'js',
          resolveDir: path.dirname(args.path),
        };
      });
    },
  }],
}).then(result => {
  if (result.warnings.length) {
    throw new Error(`Build produced ${result.warnings.length} warnings`);
  }
  console.log('frontend.js built successfully; warnings=0');
}).catch(error => {
  console.error(error);
  process.exitCode = 1;
});
