const fs = require('fs');
const path = require('path');

// Read index.html to create a complete DOM representation instead of manually maintaining one
const htmlContent = fs.readFileSync(path.resolve(__dirname, '../index.html'), 'utf8');

describe('showToast', () => {
  beforeEach(() => {
    // 1. Mock the HTML structure expected by app.js using index.html
    document.documentElement.innerHTML = htmlContent;

    // Reset modules to avoid duplicate declaration errors like "Identifier 'allGames' has already been declared"
    // Though we are injecting via script tag, JSDOM window maintains state between tests

    // Mock fetch for loadGames and checkCoreStatus which are called on DOMContentLoaded
    global.fetch = jest.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({ games: [] }),
      })
    );

    // An alternative that avoids regex and eval while still putting functions in global scope:
    const scriptContent = fs.readFileSync(path.resolve(__dirname, '../app.js'), 'utf8');

    // Execute the entire script within the jsdom window context, running only once if possible
    // or resetting window context completely. In Jest JSDOM, window is recreated if we do it right,
    // but we can also just use eval in the window context.

    // Since jest.resetModules() doesn't clear JSDOM window variables defined by script tags,
    // let's evaluate it on window explicitly in a safe way if needed, or better,
    // wrap the script in an IIFE but expose showToast.
    // Easiest is to mock the DOM, then `require('../app.js')`. But app.js is not a module.
    // Let's use `window.eval(scriptContent)` which evaluates in the global scope of JSDOM.

    try {
        window.eval(scriptContent);
    } catch (e) {
        // Handle "Identifier 'allGames' has already been declared" by only evaluating once per test suite
        // or by clearing the window scope which jest does automatically before each test *file* but not each test *case*.
    }

    // 3. Mock timers for setTimeout
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
    document.body.innerHTML = '';
    jest.restoreAllMocks();
  });

  it('should create a toast element and append it to the container', () => {
    window.showToast('Test message', 'success');

    const container = document.getElementById('toast-container');
    expect(container.children.length).toBe(1);

    const toast = container.children[0];
    expect(toast.className).toBe('toast success');
    expect(toast.innerHTML).toBe('<span>Test message</span>');
  });

  it('should use "info" as the default type if not provided', () => {
    window.showToast('Default info toast');

    const container = document.getElementById('toast-container');
    const toast = container.children[0];
    expect(toast.className).toBe('toast info');
  });

  it('should remove the toast element after the timeout', () => {
    window.showToast('Timeout test');

    const container = document.getElementById('toast-container');
    expect(container.children.length).toBe(1);

    const toast = container.children[0];

    // Fast-forward the first timeout (opacity transition)
    jest.runOnlyPendingTimers();
    expect(toast.style.opacity).toBe('0');

    // The element should still be in the DOM
    expect(container.children.length).toBe(1);

    // Fast-forward the inner timeout (removal)
    jest.runOnlyPendingTimers();

    // Now it should be removed
    expect(container.children.length).toBe(0);
  });
});
