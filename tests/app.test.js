const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

describe('getFilteredGames', () => {
    let window;
    let document;

    beforeEach(() => {
        const html = fs.readFileSync(path.resolve(__dirname, '../public/index.html'), 'utf8');
        const jsdom = new JSDOM(html, { runScripts: 'dangerously' });
        window = jsdom.window;
        document = window.document;

        const scriptCode = fs.readFileSync(path.resolve(__dirname, '../public/app.js'), 'utf8');

        const modifiedScript = scriptCode.replace(
            "window.addEventListener('DOMContentLoaded', () => {\n  loadGames();\n  checkCoreStatus();\n  loadSidebarGpu();\n});",
            ""
        );

        const scriptEl = document.createElement('script');
        scriptEl.textContent = modifiedScript;
        document.body.appendChild(scriptEl);
    });

    const runInDOM = (code) => {
        return window.eval(code);
    };

    const setupGames = () => {
        runInDOM(`
            allGames = [
                { name: 'Cyberpunk 2077', folder: 'Cyberpunk', launcher: 'Steam', installed: true, route: 'direct' },
                { name: 'The Witcher 3', folder: 'Witcher3', launcher: 'GOG', installed: false, route: 'optiscaler' },
                { name: 'Red Dead Redemption 2', folder: 'RDR2', launcher: 'Epic', installed: true, route: 'optiscaler' },
                { name: 'Cyber Hero', folder: 'CyberHero', launcher: 'Steam', installed: false, route: 'direct' }
            ];

            // Note: Our launcher options from the HTML: "all", "Steam", "Custom".
            // The tests can dynamically set values to other things, but we need to make sure
            // the DOM actually accepts the value, so we might need to add options or just use
            // valid HTML options. Wait, we can add options dynamically in the test or
            // JS doesn't validate \`select.value = 'Epic'\` if it's not an option.
            // Let's add options to avoid any issues:

            const select = document.getElementById('filter-launcher');
            const newOption1 = document.createElement('option');
            newOption1.value = 'Epic';
            select.appendChild(newOption1);

            const newOption2 = document.createElement('option');
            newOption2.value = 'GOG';
            select.appendChild(newOption2);
        `);
    };

    it('should exist', () => {
        expect(typeof window.getFilteredGames).toBe('function');
    });

    describe('Search Query Filtering', () => {
        it('should filter by search query (name match)', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = 'cyber';
                filterLauncher.value = 'all';
                filterStatus.value = 'all';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(2);
            expect(result[0].name).toBe('Cyber Hero');
            expect(result[1].name).toBe('Cyberpunk 2077');
        });

        it('should filter by search query (folder match)', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = 'witch';
                filterLauncher.value = 'all';
                filterStatus.value = 'all';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(1);
            expect(result[0].name).toBe('The Witcher 3');
        });

        it('should handle case insensitivity', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = 'CYBERPUNK';
                filterLauncher.value = 'all';
                filterStatus.value = 'all';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(1);
            expect(result[0].name).toBe('Cyberpunk 2077');
        });

        it('should ignore empty search queries', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '   ';
                filterLauncher.value = 'all';
                filterStatus.value = 'all';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(4);
        });
    });

    describe('Launcher Filtering', () => {
        it('should filter by specific launcher', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '';
                filterLauncher.value = 'Steam';
                filterStatus.value = 'all';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(2);
            expect(result[0].name).toBe('Cyber Hero');
            expect(result[1].name).toBe('Cyberpunk 2077');
        });

        it('should show all launchers when "all" is selected', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '';
                filterLauncher.value = 'all';
                filterStatus.value = 'all';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(4);
        });
    });

    describe('Status Filtering', () => {
        it('should filter by installed status', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '';
                filterLauncher.value = 'all';
                filterStatus.value = 'installed';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(2);
            expect(result.map(g => g.name)).toEqual(['Cyberpunk 2077', 'Red Dead Redemption 2']);
        });

        it('should filter by not-installed status', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '';
                filterLauncher.value = 'all';
                filterStatus.value = 'not-installed';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(2);
            expect(result.map(g => g.name)).toEqual(['Cyber Hero', 'The Witcher 3']);
        });

        it('should filter by optiscaler route', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '';
                filterLauncher.value = 'all';
                filterStatus.value = 'optiscaler';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(2);
            expect(result.map(g => g.name)).toEqual(['Red Dead Redemption 2', 'The Witcher 3']);
        });

        it('should filter by direct route', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '';
                filterLauncher.value = 'all';
                filterStatus.value = 'direct';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(2);
            expect(result.map(g => g.name)).toEqual(['Cyber Hero', 'Cyberpunk 2077']);
        });
    });

    describe('Sorting', () => {
        it('should sort by name ascending', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '';
                filterLauncher.value = 'all';
                filterStatus.value = 'all';
                sortSelect.value = 'name-asc';
                getFilteredGames();
            `);

            expect(result.map(g => g.name)).toEqual([
                'Cyber Hero',
                'Cyberpunk 2077',
                'Red Dead Redemption 2',
                'The Witcher 3'
            ]);
        });

        it('should sort by name descending', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '';
                filterLauncher.value = 'all';
                filterStatus.value = 'all';
                sortSelect.value = 'name-desc';
                getFilteredGames();
            `);

            expect(result.map(g => g.name)).toEqual([
                'The Witcher 3',
                'Red Dead Redemption 2',
                'Cyberpunk 2077',
                'Cyber Hero'
            ]);
        });

        it('should sort by installed status then name', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = '';
                filterLauncher.value = 'all';
                filterStatus.value = 'all';
                sortSelect.value = 'status';
                getFilteredGames();
            `);

            // Installed should come first, then sorted by name
            expect(result.map(g => g.name)).toEqual([
                'Cyberpunk 2077',         // installed
                'Red Dead Redemption 2',  // installed
                'Cyber Hero',             // not installed
                'The Witcher 3'           // not installed
            ]);
        });
    });

    describe('Combination Filtering', () => {
        it('should combine multiple filters', () => {
            setupGames();

            const result = runInDOM(`
                searchInput.value = 'red';
                filterLauncher.value = 'Epic';
                filterStatus.value = 'installed';
                sortSelect.value = 'name-desc';
                getFilteredGames();
            `);

            expect(result).toHaveLength(1);
            expect(result[0].name).toBe('Red Dead Redemption 2');
        });
    });
});
