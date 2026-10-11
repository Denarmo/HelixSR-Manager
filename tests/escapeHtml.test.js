const fs = require('fs');

// We need to extract the escapeHtml function from public/app.js
const appJsContent = fs.readFileSync('public/app.js', 'utf8');

// Find the escapeHtml function
const funcMatch = appJsContent.match(/function escapeHtml\([^}]+\}/);

if (!funcMatch) {
    throw new Error("Could not find escapeHtml function");
}

let escapeHtmlFunc;
eval("escapeHtmlFunc = " + funcMatch[0]);

describe('escapeHtml', () => {
    it('returns empty string when given falsy values', () => {
        expect(escapeHtmlFunc(null)).toBe('');
        expect(escapeHtmlFunc(undefined)).toBe('');
        expect(escapeHtmlFunc('')).toBe('');
    });

    it('returns the same string when there are no special characters', () => {
        expect(escapeHtmlFunc('hello world')).toBe('hello world');
        expect(escapeHtmlFunc('123')).toBe('123');
    });

    it('escapes ampersands', () => {
        expect(escapeHtmlFunc('Jack & Jill')).toBe('Jack &amp; Jill');
    });

    it('escapes less than signs', () => {
        expect(escapeHtmlFunc('<script>')).toBe('&lt;script&gt;');
    });

    it('escapes greater than signs', () => {
        expect(escapeHtmlFunc('5 > 3')).toBe('5 &gt; 3');
    });

    it('escapes double quotes', () => {
        expect(escapeHtmlFunc('"quoted"')).toBe('&quot;quoted&quot;');
    });

    it('escapes multiple special characters', () => {
        expect(escapeHtmlFunc('<div class="test">&</div>')).toBe('&lt;div class=&quot;test&quot;&gt;&amp;&lt;/div&gt;');
    });
});
