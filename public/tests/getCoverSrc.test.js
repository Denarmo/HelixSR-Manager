/**
 * @jest-environment jsdom
 */

const fs = require('fs');
const path = require('path');

// To safely test just getCoverSrc without the entire app.js throwing DOM errors,
// we extract the function dynamically from app.js using regex.

const appJsPath = path.resolve(__dirname, '../app.js');
const appJsCode = fs.readFileSync(appJsPath, 'utf8');

// Match the getCoverSrc function definition
const functionRegex = /function getCoverSrc\s*\([^)]*\)\s*{[\s\S]*?return null;\n}/;
const match = appJsCode.match(functionRegex);

if (!match) {
  throw new Error("Could not find getCoverSrc function in app.js");
}

// Eval the function in an isolated scope
let getCoverSrc;
eval(`getCoverSrc = ${match[0]}`);

describe('getCoverSrc', () => {
  it('should return null if game.cover is missing', () => {
    expect(getCoverSrc({})).toBeNull();
  });

  it('should return encoded path for local cover', () => {
    const game = {
      cover: {
        type: 'local',
        path: 'C:\\test\\image.jpg'
      }
    };
    const b64 = btoa('C:\\test\\image.jpg');
    const expected = `/api/steam-image?path=${encodeURIComponent(b64)}`;
    expect(getCoverSrc(game)).toBe(expected);
  });

  it('should return URL for remote cover', () => {
    const game = {
      cover: {
        type: 'remote',
        url: 'https://example.com/image.jpg'
      }
    };
    expect(getCoverSrc(game)).toBe('https://example.com/image.jpg');
  });

  it('should return null if game.cover.type is unknown', () => {
    const game = {
      cover: {
        type: 'unknown'
      }
    };
    expect(getCoverSrc(game)).toBeNull();
  });
});
