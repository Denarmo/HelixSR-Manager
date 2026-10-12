// HelixSR Swapper - Client Frontend
let allGames = [];
let currentGame = null;
let currentView = 'grid';
let activeLogs = { helixsrLog: '', optiscalerLog: '' };
let currentLogType = 'helix';
// Filled from /api/core/status; defaults match the bundled release
let coreInfo = { version: '1.8.1', appVersion: '1.0.0', dlssLoaderAvailable: true };

function updateVersionTag() {
  const tag = document.getElementById('app-version-tag');
  if (tag) tag.textContent = `Manager v${coreInfo.appVersion} · Core v${coreInfo.version}`;
}

// DOM Elements
const gamesGrid = document.getElementById('games-grid');
const gamesList = document.getElementById('games-list');
const gamesTableBody = document.getElementById('games-table-body');
const gamesLoading = document.getElementById('games-loading');
const gamesEmpty = document.getElementById('games-empty');
const gamesCountBadge = document.getElementById('games-count-badge');
const coreStatusDot = document.getElementById('core-status-dot');
const searchInput = document.getElementById('search-input');
const clearSearchBtn = document.getElementById('clear-search');
const filterLauncher = document.getElementById('filter-launcher');
const filterStatus = document.getElementById('filter-status');
const sortSelect = document.getElementById('sort-select');

// Drawer Elements
const drawerBackdrop = document.getElementById('drawer-backdrop');
const gameDrawer = document.getElementById('game-drawer');
const btnCloseDrawer = document.getElementById('btn-close-drawer');
const drawerGameTitle = document.getElementById('drawer-game-title');
const drawerHeroImg = document.getElementById('drawer-hero-img');
const drawerThumb = document.getElementById('drawer-thumb');
const drawerPlatformBadge = document.getElementById('drawer-platform-badge');
const drawerRouteBadge = document.getElementById('drawer-route-badge');
const drawerStatusBadge = document.getElementById('drawer-status-badge');
const drawerBtnInstall = document.getElementById('drawer-btn-install');
const drawerInstallText = document.getElementById('drawer-install-text');
const drawerBtnUninstall = document.getElementById('drawer-btn-uninstall');
const drawerBtnLaunch = document.getElementById('drawer-btn-launch');
const drawerBtnOpenGame = document.getElementById('drawer-btn-open-game');
const drawerBtnOpenBackup = document.getElementById('drawer-btn-open-backup');
const drawerBtnOpenMyfsr = document.getElementById('drawer-btn-open-myfsr');
const drawerValExe = document.getElementById('drawer-val-exe');
const drawerValPath = document.getElementById('drawer-val-path');
const drawerValInputs = document.getElementById('drawer-val-inputs');
const drawerValMethod = document.getElementById('drawer-val-method');
const drawerValBackup = document.getElementById('drawer-val-backup');
const iniEditorText = document.getElementById('ini-editor-text');
const btnSaveIni = document.getElementById('btn-save-ini');
const logOutputText = document.getElementById('log-output-text');
const btnRefreshLogs = document.getElementById('btn-refresh-logs');

// Toast Notification
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Navigation Tabs
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const tabId = btn.dataset.tab;
    const pane = document.getElementById(`tab-${tabId}`);
    if (pane) pane.classList.add('active');

    if (tabId === 'core') checkCoreStatus();
    if (tabId === 'about') loadSystemInfo();
  });
});

// View Toggle (Grid vs List)
document.getElementById('btn-view-grid').addEventListener('click', () => {
  currentView = 'grid';
  document.getElementById('btn-view-grid').classList.add('active');
  document.getElementById('btn-view-list').classList.remove('active');
  gamesGrid.style.display = 'grid';
  gamesList.style.display = 'none';
  renderGames();
});

document.getElementById('btn-view-list').addEventListener('click', () => {
  currentView = 'list';
  document.getElementById('btn-view-list').classList.add('active');
  document.getElementById('btn-view-grid').classList.remove('active');
  gamesGrid.style.display = 'none';
  gamesList.style.display = 'block';
  renderGames();
});

// Fetch Games from Server
async function loadGames() {
  gamesLoading.style.display = 'block';
  gamesEmpty.style.display = 'none';
  try {
    const res = await fetch('/api/games');
    const data = await res.json();
    allGames = data.games || [];
    gamesCountBadge.textContent = allGames.length;
    renderGames();
    populateDlssCandidates(allGames);
  } catch (err) {
    showToast('Failed to load games: ' + err.message, 'error');
  } finally {
    gamesLoading.style.display = 'none';
  }
}

// Filter and Sort Games
function getFilteredGames() {
  const query = searchInput.value.trim().toLowerCase();
  const launcher = filterLauncher.value;
  const status = filterStatus.value;
  const sort = sortSelect.value;

  let filtered = allGames.filter(g => {
    if (query && !g.name.toLowerCase().includes(query) && !g.folder.toLowerCase().includes(query)) {
      return false;
    }
    if (launcher !== 'all' && g.launcher !== launcher) {
      return false;
    }
    if (status === 'installed' && !g.installed) return false;
    if (status === 'not-installed' && g.installed) return false;
    if (status === 'optiscaler' && g.route !== 'optiscaler') return false;
    if (status === 'direct' && g.route !== 'direct') return false;
    return true;
  });

  filtered.sort((a, b) => {
    if (sort === 'name-asc') return a.name.localeCompare(b.name);
    if (sort === 'name-desc') return b.name.localeCompare(a.name);
    if (sort === 'status') {
      if (a.installed === b.installed) return a.name.localeCompare(b.name);
      return a.installed ? -1 : 1;
    }
    return 0;
  });

  return filtered;
}

function getCoverSrc(game) {
  if (game.cover) {
    if (game.cover.type === 'local') {
      const b64 = btoa(game.cover.path);
      return `/api/steam-image?path=${encodeURIComponent(b64)}`;
    }
    if (game.cover.type === 'remote') {
      return game.cover.url;
    }
  }
  return null;
}

// Render Games Grid / List
function renderGames() {
  const games = getFilteredGames();
  gamesEmpty.style.display = games.length === 0 ? 'block' : 'none';

  if (currentView === 'grid') {
    gamesGrid.innerHTML = '';
    for (const g of games) {
      const card = document.createElement('div');
      card.className = `game-card ${g.installed ? 'installed' : ''}`;
      card.onclick = () => openGameDrawer(g);

      const coverSrc = getCoverSrc(g);
      let posterHtml = '';
      if (coverSrc) {
        posterHtml = `
          <div class="poster-wrap">
            <img class="poster-img" src="${coverSrc}" alt="${g.name}" loading="lazy" onerror="this.parentElement.innerHTML='<div class=\\'poster-fallback\\'><div class=\\'fallback-title\\'>${escapeHtml(g.name)}</div></div>'">
            <div class="poster-top-badges">
              <span class="platform-badge">${g.launcher}</span>
              <div class="inputs-pills">
                ${g.inputs.map(inp => `<span class="pill-tag ${inp.toLowerCase().replace(' ', '')}">${inp}</span>`).join('')}
              </div>
            </div>
          </div>
        `;
      } else {
        posterHtml = `
          <div class="poster-wrap">
            <div class="poster-fallback">
              <div class="fallback-title">${escapeHtml(g.name)}</div>
            </div>
            <div class="poster-top-badges">
              <span class="platform-badge">${g.launcher}</span>
              <div class="inputs-pills">
                ${g.inputs.map(inp => `<span class="pill-tag ${inp.toLowerCase().replace(' ', '')}">${inp}</span>`).join('')}
              </div>
            </div>
          </div>
        `;
      }

      const statusHtml = g.installed
        ? `<div class="card-status-pill active"><span class="status-dot-sm"></span>HelixSR Active (${g.version || coreInfo.version})</div>`
        : `<div class="card-status-pill"><span class="status-dot-sm"></span>Not Installed</div>`;

      card.innerHTML = `
        ${posterHtml}
        <div class="card-details">
          <div class="card-title" title="${escapeHtml(g.name)}">${escapeHtml(g.name)}</div>
          ${statusHtml}
        </div>
      `;
      gamesGrid.appendChild(card);
    }
  } else {
    // List View
    gamesTableBody.innerHTML = '';
    for (const g of games) {
      const tr = document.createElement('tr');
      const coverSrc = getCoverSrc(g);
      const imgHtml = coverSrc
        ? `<img class="table-thumb" src="${coverSrc}" alt="" onerror="this.style.display='none'">`
        : `<div class="table-thumb" style="background:#222;"></div>`;

      tr.innerHTML = `
        <td>${imgHtml}</td>
        <td><strong>${escapeHtml(g.name)}</strong></td>
        <td><span class="badge">${g.launcher}</span></td>
        <td>${g.inputs.map(inp => `<span class="pill-tag ${inp.toLowerCase().replace(' ', '')}">${inp}</span>`).join(' ')}</td>
        <td>${g.route === 'optiscaler' ? 'OptiScaler (DLSS)' : (g.route === 'dlss' ? 'DLSS Loader (Experimental)' : 'Direct FSR 3.1')}</td>
        <td>
          <span class="badge ${g.installed ? 'badge-success' : ''}">
            ${g.installed ? `Active (${g.version || coreInfo.version})` : 'Not Installed'}
          </span>
        </td>
        <td style="text-align: right;">
          <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); openGameDrawerByFolder('${escapeHtml(g.folder)}')">Manage</button>
        </td>
      `;
      tr.onclick = () => openGameDrawer(g);
      gamesTableBody.appendChild(tr);
    }
  }
}

// Drawer Flyout
function openGameDrawerByFolder(folder) {
  const g = allGames.find(x => x.folder === folder);
  if (g) openGameDrawer(g);
}

function populateDrawerMethodOptions(game) {
  const sel = document.getElementById('drawer-install-method');
  const fgSel = document.getElementById('drawer-fg-mode');
  const chkFake = document.getElementById('drawer-chk-fakenvapi');
  const chkRef = document.getElementById('drawer-chk-reframework');
  if (!sel) return;

  sel.innerHTML = '';
  const hasNativeFsr = game.fsrTargets && game.fsrTargets.length > 0;
  const directLabel = hasNativeFsr
    ? 'Direct FSR 3.1 Replacement (Native FSR 3.1 DLLs)'
    : 'Direct FSR 3.1 Replacement (Standalone FidelityFX DLLs)';

  const optiOptions = [
    ['dxgi.dll', 'OptiScaler Proxy — dxgi.dll (Recommended DLSS/XeSS/FSR2 Hook)'],
    ['winmm.dll', 'OptiScaler Proxy — winmm.dll (Compatibility Hook)'],
    ['version.dll', 'OptiScaler Proxy — version.dll (Alternative Hook)'],
    ['dbghelp.dll', 'OptiScaler Proxy — dbghelp.dll (Alternative Hook)'],
    ['d3d12.dll', 'OptiScaler Proxy — d3d12.dll (Direct3D 12 Hook)'],
    ['wininet.dll', 'OptiScaler Proxy — wininet.dll (Alternative Hook)'],
    ['winhttp.dll', 'OptiScaler Proxy — winhttp.dll (Alternative Hook)'],
    ['OptiScaler.asi', 'OptiScaler ASI Plugin — OptiScaler.asi (ASI Loader)']
  ];

  // Default / Recommended: OptiScaler dxgi.dll first
  const optDxgi = document.createElement('option');
  optDxgi.value = 'optiscaler:dxgi.dll';
  optDxgi.textContent = optiOptions[0][1];
  sel.appendChild(optDxgi);

  // Direct FSR option
  const optDirect = document.createElement('option');
  optDirect.value = 'direct';
  optDirect.textContent = directLabel;
  sel.appendChild(optDirect);

  // Other OptiScaler hooks
  for (let i = 1; i < optiOptions.length; i++) {
    const [dll, label] = optiOptions[i];
    const o = document.createElement('option');
    o.value = `optiscaler:${dll}`;
    o.textContent = label;
    sel.appendChild(o);
  }

  // EXPERIMENTAL (HelixSR 1.8.1): DLSS loader route, only for games with a DLSS input
  const hasDlssInput = Array.isArray(game.inputs) && game.inputs.includes('DLSS');
  if ((hasDlssInput && coreInfo.dlssLoaderAvailable) || game.route === 'dlss') {
    const o = document.createElement('option');
    o.value = 'dlss';
    o.textContent = 'DLSS Loader — dxgi.dll + nvngx.dll (EXPERIMENTAL, no OptiScaler)';
    sel.appendChild(o);
  }

  const targetVal = game.route === 'direct' ? 'direct' : (game.route === 'dlss' ? 'dlss' : `optiscaler:${game.optiDllName || 'dxgi.dll'}`);
  sel.value = targetVal;

  if (fgSel) {
    fgSel.innerHTML = '';
    const fgOptions = [
      ['auto', 'Frame Gen: Game Default / Pass-Through'],
      ['dlssg_xefg', 'DLSS-G Hook → Intel XeFG (AI Neural Frame Gen on AMD)'],
      ['dlssg_fsrfg', 'DLSS-G Hook → AMD FidelityFX FG (FSR 3.1 / 4.0 FG)'],
      ['dlssg_nukems', "DLSS-G Hook → Nukem's dlssg-to-fsr3 (Streamline Swapchain)"],
      ['optifg_fsrfg', 'Universal OptiFG (Upscaler Hook + HUDFix → FSR-FG)']
    ];
    for (const [val, label] of fgOptions) {
      const o = document.createElement('option');
      o.value = val;
      o.textContent = label;
      fgSel.appendChild(o);
    }
    fgSel.value = game.fgMode || 'auto';
  }

  if (chkFake) chkFake.checked = game.useFakeNvapi !== false;
  if (chkRef) chkRef.checked = !!game.installReFramework;
  updateDrawerMethodSummary();
}

function updateDrawerMethodSummary() {
  if (!currentGame) return;
  const sel = document.getElementById('drawer-install-method');
  const fgWrap = document.getElementById('drawer-fg-wrap');
  const fgSel = document.getElementById('drawer-fg-mode');
  const hint = document.getElementById('drawer-method-hint');
  const fakeWrap = document.getElementById('drawer-fakenvapi-wrap');
  const chkFake = document.getElementById('drawer-chk-fakenvapi');
  const chkRef = document.getElementById('drawer-chk-reframework');
  const protonBox = document.getElementById('drawer-proton-box');
  const protonCmd = document.getElementById('drawer-proton-cmd');
  const instructionsBox = document.getElementById('drawer-instructions-box');

  const val = sel ? sel.value : 'optiscaler:dxgi.dll';
  if (val === 'direct') {
    currentGame.route = 'direct';
  } else if (val === 'dlss') {
    currentGame.route = 'dlss';
  } else if (val.startsWith('optiscaler:')) {
    currentGame.route = 'optiscaler';
    currentGame.optiDllName = val.substring('optiscaler:'.length);
  }
  currentGame.fgMode = fgSel ? fgSel.value : 'auto';
  if (currentGame.fgMode.startsWith('dlssg_') && chkFake) {
    chkFake.checked = true;
  }
  currentGame.useFakeNvapi = chkFake ? chkFake.checked : true;
  currentGame.installReFramework = chkRef ? chkRef.checked : false;

  const isOpti = currentGame.route === 'optiscaler';
  const isDlss = currentGame.route === 'dlss';
  const optiDll = currentGame.optiDllName || 'dxgi.dll';
  if (fgWrap) fgWrap.style.display = isOpti ? 'block' : 'none';
  if (fakeWrap) fakeWrap.style.display = isOpti ? 'flex' : 'none';

  const fgMap = {
    dlssg_xefg: ' + XeFG',
    dlssg_fsrfg: ' + FSR-FG',
    dlssg_nukems: ' + NukemFG',
    optifg_fsrfg: ' + OptiFG'
  };
  const fgTag = isOpti ? (fgMap[currentGame.fgMode] || '') : '';
  drawerRouteBadge.textContent = isOpti ? `OptiScaler (${optiDll}${fgTag})` : (isDlss ? 'DLSS Loader (Experimental)' : 'Direct (FSR 3.1)');
  if (currentGame.installReFramework) drawerRouteBadge.textContent += ' + REFramework';

  // Compute Proton Launch Options
  const dlls = [];
  if (isOpti && optiDll.toLowerCase().endsWith('.dll')) dlls.push(optiDll.slice(0, -4));
  if (isDlss) dlls.push('dxgi');
  if (currentGame.installReFramework && !dlls.includes('dinput8')) dlls.push('dinput8');
  if (dlls.length > 0 && protonBox && protonCmd) {
    protonBox.style.display = 'block';
    protonCmd.textContent = `WINEDLLOVERRIDES="${dlls.join(',')}=n,b" %command%`;
  } else if (protonBox) {
    protonBox.style.display = 'none';
  }

  if (isDlss) {
    if (hint) hint.textContent = 'EXPERIMENTAL (HelixSR 1.8.1): puts HelixSR\'s DLSS loader (dxgi.dll) and HelixSR as nvngx.dll next to the game .exe, so the game\'s own DLSS option runs HelixSR without OptiScaler. Tested upstream in very few games (Linux/Proton). Existing files are backed up. Never use in online games with anti-cheat (ban risk).';
    drawerValMethod.textContent = currentGame.installReFramework
      ? 'DLSS Loader (Experimental) + REFramework Nightly (dinput8.dll)'
      : 'DLSS Loader (Experimental - dxgi.dll + nvngx.dll)';
    if (instructionsBox) {
      instructionsBox.innerHTML = `
        <ol>
          <li>Click <strong>Install HelixSR</strong> and confirm the experimental warning.</li>
          <li>On SteamOS / Linux, paste the <strong>Proton Launch Option</strong> above into Steam game properties.</li>
          <li>Launch the game and select <strong>NVIDIA DLSS</strong> in Graphics settings - HelixSR runs in its place.</li>
          <li>If the game does not start or DLSS is missing, uninstall and use the OptiScaler route instead.</li>
        </ol>
      `;
    }
  } else if (isOpti) {
    let fgNote = '';
    if (currentGame.fgMode === 'dlssg_xefg') fgNote = ' Routes in-game DLSS Frame Generation to Intel XeSS-FG (AI optical flow on AMD/Intel).';
    else if (currentGame.fgMode === 'dlssg_fsrfg') fgNote = ' Routes in-game DLSS Frame Generation to AMD FidelityFX Frame Generation.';
    else if (currentGame.fgMode === 'dlssg_nukems') fgNote = " Routes in-game DLSS Frame Generation via Nukem's dlssg-to-fsr3 swapchain.";
    else if (currentGame.fgMode === 'optifg_fsrfg') fgNote = ' Enables Universal OptiFG + HUDFix using upscaler motion vectors & depth.';

    if (hint) hint.textContent = `Injects OptiScaler via ${optiDll} and routes DLSS/XeSS/FSR 2 inputs to HelixSR.${fgNote} Press Insert in-game to open the OptiScaler menu.`;
    drawerValMethod.textContent = currentGame.installReFramework
      ? `OptiScaler (${optiDll}${fgTag}) + REFramework Nightly (dinput8.dll)`
      : `OptiScaler Injection (${optiDll}${fgTag} — Select DLSS in game)`;
    if (instructionsBox) {
      instructionsBox.innerHTML = `
        <ol>
          <li>Choose your OptiScaler hook (<code>${optiDll}</code>) and Frame Generation mode, then click <strong>Install HelixSR</strong>.</li>
          <li>On SteamOS / Linux, paste the <strong>Proton Launch Option</strong> above into Steam game properties if needed.</li>
          <li>Launch the game and select <strong>NVIDIA DLSS</strong> (and enable DLSS Frame Generation if using a DLSS-G hook) in Graphics settings.</li>
          <li>Press <kbd>Insert</kbd> in-game to open OptiScaler's HUD and customize HelixSR &amp; Frame Generation.</li>
        </ol>
      `;
    }
  } else {
    const hasNative = currentGame.fsrTargets && currentGame.fsrTargets.length > 0;
    if (hint) hint.textContent = hasNative
      ? `Replaces ${currentGame.fsrTargets.length} native FidelityFX DX12 DLL(s) directly (*.original.dll backed up). Zero proxy hook overhead.`
      : 'Deploys standalone amd_fidelityfx_upscaler_dx12.dll & amd_fidelityfx_dx12.dll directly next to the game executable.';
    drawerValMethod.textContent = currentGame.installReFramework
      ? 'Direct FSR 3.1 Replacement + REFramework Nightly (dinput8.dll)'
      : 'Direct DLL Replacement (*.original.dll kept)';
    if (instructionsBox) {
      instructionsBox.innerHTML = `
        <ol>
          <li>Click <strong>Install HelixSR</strong> above to replace the FidelityFX upscaler DLL with HelixSR.</li>
          <li>Start the game and enable <strong>AMD FSR 3 / FSR 3.1</strong> in graphics settings.</li>
          <li>HelixSR runs automatically in place of FSR 3.1 with zero proxy hook overhead!</li>
        </ol>
      `;
    }
  }
}

document.getElementById('drawer-install-method')?.addEventListener('change', updateDrawerMethodSummary);
document.getElementById('drawer-fg-mode')?.addEventListener('change', updateDrawerMethodSummary);
document.getElementById('drawer-chk-fakenvapi')?.addEventListener('change', updateDrawerMethodSummary);
document.getElementById('drawer-chk-reframework')?.addEventListener('change', updateDrawerMethodSummary);
document.getElementById('drawer-btn-copy-proton')?.addEventListener('click', () => {
  const cmd = document.getElementById('drawer-proton-cmd')?.textContent;
  if (cmd && navigator.clipboard) {
    navigator.clipboard.writeText(cmd);
    showToast('Copied Proton Launch Option to clipboard!', 'success');
  }
});

function openGameDrawer(game) {
  currentGame = game;
  drawerGameTitle.textContent = game.name;
  drawerPlatformBadge.textContent = game.launcher;

  const coverSrc = getCoverSrc(game);
  drawerThumb.src = coverSrc || '';
  drawerThumb.style.display = coverSrc ? 'block' : 'none';

  if (game.hero && game.hero.type === 'local') {
    const b64 = btoa(game.hero.path);
    drawerHeroImg.style.backgroundImage = `url('/api/steam-image?path=${encodeURIComponent(b64)}')`;
  } else if (game.hero && game.hero.type === 'remote') {
    drawerHeroImg.style.backgroundImage = `url('${game.hero.url}')`;
  } else {
    drawerHeroImg.style.backgroundImage = 'none';
  }

  // Update Status Pill
  if (game.installed) {
    drawerStatusBadge.className = 'badge badge-success';
    drawerStatusBadge.textContent = `HelixSR Installed (${game.version || coreInfo.version})`;
    drawerBtnInstall.className = 'btn btn-secondary';
    drawerInstallText.textContent = 'Reinstall / Update';
    drawerBtnUninstall.style.display = 'inline-flex';
  } else {
    drawerStatusBadge.className = 'badge';
    drawerStatusBadge.textContent = 'Not Installed';
    drawerBtnInstall.className = 'btn btn-primary';
    drawerInstallText.textContent = 'Install HelixSR';
    drawerBtnUninstall.style.display = 'none';
  }

  drawerValExe.textContent = game.exeName || 'Not detected';
  drawerValPath.textContent = game.exeFolder || game.folder;
  drawerValPath.title = game.exeFolder || game.folder;
  drawerValInputs.textContent = game.inputs.length > 0 ? game.inputs.join(', ') : 'FSR 3.1 DLL Replacement';

  populateDrawerMethodOptions(game);

  // Load Logs and INI
  fetchGameLogs(game.folder);

  // Open Drawer
  drawerBackdrop.classList.add('open');
  gameDrawer.classList.add('open');
}

function closeGameDrawer() {
  drawerBackdrop.classList.remove('open');
  gameDrawer.classList.remove('open');
  currentGame = null;
}

drawerBackdrop.addEventListener('click', closeGameDrawer);
btnCloseDrawer.addEventListener('click', closeGameDrawer);

// Drawer Action Handlers
drawerBtnInstall.addEventListener('click', async () => {
  if (!currentGame) return;
  if (currentGame.route === 'dlss' && !confirm(
    'EXPERIMENTAL: DLSS Loader route (HelixSR ' + coreInfo.version + ').\n\n' +
    'This places HelixSR\'s DLSS loader as dxgi.dll and HelixSR as nvngx.dll next to the game\'s .exe, without OptiScaler. ' +
    'It is new upstream and may not work in every game.\n\n' +
    'Do NOT use it in online games with anti-cheat - injected DLLs can get your account banned.\n\nContinue?'
  )) return;
  drawerBtnInstall.disabled = true;
  drawerInstallText.textContent = 'Installing...';
  try {
    const res = await fetch('/api/games/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gameFolder: currentGame.folder,
        route: currentGame.route,
        optiDllName: currentGame.optiDllName,
        fgMode: currentGame.fgMode,
        useFakeNvapi: currentGame.useFakeNvapi,
        installReFramework: currentGame.installReFramework
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      await loadGames();
      const updated = allGames.find(x => x.folder === currentGame.folder);
      if (updated) openGameDrawer(updated);
    } else {
      showToast('Install failed: ' + (data.error || 'Unknown error'), 'error');
    }
  } catch (err) {
    showToast('Install failed: ' + err.message, 'error');
  } finally {
    drawerBtnInstall.disabled = false;
  }
});

drawerBtnUninstall.addEventListener('click', async () => {
  if (!currentGame) return;
  if (!confirm(`Restore original files and uninstall HelixSR from ${currentGame.name}?`)) return;

  drawerBtnUninstall.disabled = true;
  try {
    const res = await fetch('/api/games/uninstall', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gameFolder: currentGame.folder })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      await loadGames();
      const updated = allGames.find(x => x.folder === currentGame.folder);
      if (updated) openGameDrawer(updated);
    } else {
      showToast('Uninstall failed: ' + (data.error || 'Unknown error'), 'error');
    }
  } catch (err) {
    showToast('Uninstall failed: ' + err.message, 'error');
  } finally {
    drawerBtnUninstall.disabled = false;
  }
});

drawerBtnLaunch.addEventListener('click', async () => {
  if (!currentGame) return;
  try {
    const res = await fetch('/api/games/launch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gameFolder: currentGame.folder })
    });
    const data = await res.json();
    if (data.success) showToast(data.message, 'success');
  } catch (err) {
    showToast('Failed to launch game: ' + err.message, 'error');
  }
});

drawerBtnOpenGame.addEventListener('click', () => {
  if (currentGame) openFolder(currentGame.exeFolder || currentGame.folder);
});

drawerBtnOpenBackup.addEventListener('click', () => {
  if (currentGame && currentGame.exeFolder) {
    const sep = currentGame.exeFolder.includes('/') ? '/' : '\\';
    openFolder(`${currentGame.exeFolder}${sep}HelixSR${sep}backup`);
  }
});

drawerBtnOpenMyfsr.addEventListener('click', () => {
  if (currentGame && currentGame.exeFolder) {
    const sep = currentGame.exeFolder.includes('/') ? '/' : '\\';
    openFolder(`${currentGame.exeFolder}${sep}HelixSR${sep}my-fsr`);
  }
});

document.getElementById('drawer-btn-clear-cache')?.addEventListener('click', async () => {
  if (!currentGame) return;
  try {
    const res = await fetch('/api/games/clear-cache', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gameFolder: currentGame.folder })
    });
    const data = await res.json();
    showToast(data.message || 'Shader cache cleared!', data.cleared ? 'success' : 'info');
  } catch (err) {
    showToast('Failed to clear cache: ' + err.message, 'error');
  }
});

async function openFolder(folderPath) {
  try {
    await fetch('/api/games/open-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: folderPath })
    });
  } catch (err) {
    showToast('Could not open folder: ' + err.message, 'error');
  }
}

// Drawer Sub Tabs
const drawerTabBtns = document.querySelectorAll('.drawer-tab-btn');
const dtabPanes = document.querySelectorAll('.dtab-pane');
drawerTabBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    drawerTabBtns.forEach(b => b.classList.remove('active'));
    dtabPanes.forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const target = document.getElementById(`dtab-${btn.dataset.dtab}`);
    if (target) target.classList.add('active');
  });
});

async function fetchGameLogs(folder) {
  try {
    const res = await fetch(`/api/games/logs?folder=${encodeURIComponent(folder)}`);
    const data = await res.json();
    activeLogs.helixsrLog = data.helixsrLog || 'No helixsr.log found yet.';
    activeLogs.optiscalerLog = data.optiscalerLog || 'No OptiScaler.log found yet.';
    iniEditorText.value = data.optiscalerIni || '';
    updateLogView();
  } catch (e) {}
}

function updateLogView() {
  logOutputText.textContent = currentLogType === 'helix' ? activeLogs.helixsrLog : activeLogs.optiscalerLog;
}

document.querySelectorAll('.log-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.log-tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentLogType = btn.dataset.logtype;
    updateLogView();
  });
});

btnRefreshLogs.addEventListener('click', () => {
  if (currentGame) fetchGameLogs(currentGame.folder);
});

btnSaveIni.addEventListener('click', async () => {
  if (!currentGame) return;
  try {
    const res = await fetch('/api/games/save-ini', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gameFolder: currentGame.folder, content: iniEditorText.value })
    });
    const data = await res.json();
    if (data.success) showToast('OptiScaler.ini saved successfully!', 'success');
  } catch (err) {
    showToast('Failed to save INI: ' + err.message, 'error');
  }
});

// Refresh / Scan Button
document.getElementById('btn-refresh').addEventListener('click', async () => {
  const icon = document.querySelector('.spin-target');
  icon.classList.add('spinning');
  try {
    const res = await fetch('/api/scan', { method: 'POST' });
    const data = await res.json();
    allGames = data.games || [];
    gamesCountBadge.textContent = allGames.length;
    renderGames();
    showToast(`Scan complete: found ${allGames.length} games.`, 'success');
  } catch (e) {
    showToast('Scan failed', 'error');
  } finally {
    icon.classList.remove('spinning');
  }
});

// Install All / Uninstall All
document.getElementById('btn-install-all').addEventListener('click', async () => {
  if (!confirm('Install HelixSR on all detected games that do not have it yet?')) return;
  showToast('Starting batch installation...', 'info');
  try {
    const res = await fetch('/api/games/install-all', { method: 'POST' });
    const data = await res.json();
    showToast('Batch installation finished!', 'success');
    await loadGames();
  } catch (err) {
    showToast('Batch install failed: ' + err.message, 'error');
  }
});

document.getElementById('btn-uninstall-all').addEventListener('click', async () => {
  if (!confirm('Uninstall HelixSR and restore original files on all installed games?')) return;
  showToast('Restoring all games...', 'info');
  try {
    const res = await fetch('/api/games/uninstall-all', { method: 'POST' });
    const data = await res.json();
    showToast('All games restored to original.', 'success');
    await loadGames();
  } catch (err) {
    showToast('Batch restore failed: ' + err.message, 'error');
  }
});

// Core & Network Weights Status
async function checkCoreStatus() {
  try {
    const res = await fetch('/api/core/status');
    const data = await res.json();

    const dotWeights = document.getElementById('dot-weights');
    const dotKernels = document.getElementById('dot-kernels');
    const dotToolchain = document.getElementById('dot-toolchain');
    const valWeights = document.getElementById('val-weights-size');
    const valKernels = document.getElementById('val-kernels-size');
    const valToolchain = document.getElementById('val-toolchain-status');
    const badge = document.getElementById('core-weights-badge');

    if (data.version) coreInfo.version = data.version;
    if (data.appVersion) coreInfo.appVersion = data.appVersion;
    if (data.coreDir) coreInfo.coreDir = data.coreDir;
    if (typeof data.dlssLoaderAvailable === 'boolean') coreInfo.dlssLoaderAvailable = data.dlssLoaderAvailable;
    updateVersionTag();

    const mb = (n) => `${(n / (1024 * 1024)).toFixed(2)} MB`;
    if (data.weightsBuilt) {
      coreStatusDot.className = 'status-dot active';
      badge.textContent = 'Network Ready';
      badge.className = 'badge badge-success';
      dotWeights.className = 'dot done';
      dotKernels.className = 'dot done';
      if (data.networkEmbedded) {
        valWeights.textContent = `${mb(data.weightsSize)} (embedded in DLL)`;
        valKernels.textContent = `${mb(data.kernelsSize)} (embedded in DLL)`;
      } else {
        valWeights.textContent = `${mb(data.weightsSize)} (Ready)`;
        valKernels.textContent = `${mb(data.kernelsSize)} (Ready)`;
      }
    } else {
      coreStatusDot.className = 'status-dot';
      badge.textContent = 'Compilation Required';
      badge.className = 'badge';
      dotWeights.className = 'dot';
      dotKernels.className = 'dot';
      valWeights.textContent = 'Missing (Run Compiler)';
      valKernels.textContent = 'Missing (Run Compiler)';
    }

    if (data.hasPython && data.hasDxc) {
      dotToolchain.className = 'dot done';
      valToolchain.textContent = 'Installed in LocalAppData';
    } else {
      dotToolchain.className = 'dot';
      valToolchain.textContent = 'Will download automatically on first build';
    }
  } catch (e) {}
}

function populateDlssCandidates(games) {
  const select = document.getElementById('dlss-source-select');
  const hint = document.getElementById('dlss-detected-hint');
  select.innerHTML = '<option value="">Download automatically from NVIDIA GitHub</option>';
  const candidates = [];
  for (const g of games) {
    if (g.foundNvngxDlssPath) {
      candidates.push({ game: g.name, path: g.foundNvngxDlssPath });
    }
  }
  if (candidates.length > 0) {
    hint.textContent = `Found ${candidates.length} local copies of nvngx_dlss.dll in your library!`;
    for (const c of candidates) {
      const opt = document.createElement('option');
      opt.value = c.path;
      opt.textContent = `Use from ${c.game} (${c.path})`;
      select.appendChild(opt);
    }
  } else {
    hint.textContent = 'No local DLSS 310.7.0 found. Will download from NVIDIA GitHub.';
  }
}

// Network Build Trigger & EventSource
document.getElementById('btn-start-build').addEventListener('click', async () => {
  const dlssPath = document.getElementById('dlss-source-select').value;
  const wave64 = document.getElementById('check-wave64').checked;
  const consoleOutput = document.getElementById('console-output');
  consoleOutput.textContent = 'Starting build process...\n';

  try {
    const res = await fetch('/api/core/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dlssPath, wave64, rebuild: true })
    });
    const data = await res.json();
    if (data.success) {
      showToast('Compilation started!', 'info');
      connectBuildEvents();
    } else {
      showToast('Build error: ' + data.error, 'error');
    }
  } catch (err) {
    showToast('Failed to trigger build: ' + err.message, 'error');
  }
});

function connectBuildEvents() {
  const consoleOutput = document.getElementById('console-output');
  const evt = new EventSource('/api/core/build-events');
  evt.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      consoleOutput.textContent += data.log + '\n';
      consoleOutput.scrollTop = consoleOutput.scrollHeight;
      if (data.log.includes('Build finished successfully!')) {
        showToast('HelixSR network compiled successfully!', 'success');
        checkCoreStatus();
      }
    } catch (err) {}
  };
  evt.onerror = () => {
    evt.close();
  };
}

document.getElementById('btn-clear-console').addEventListener('click', () => {
  document.getElementById('console-output').textContent = 'Console cleared.';
});

document.getElementById('btn-open-global-myfsr').addEventListener('click', () => {
  if (coreInfo.coreDir) {
    const sep = coreInfo.coreDir.includes('/') ? '/' : '\\';
    openFolder(`${coreInfo.coreDir}${sep}my-fsr`);
  } else {
    openFolder(`helixsr_core\\HelixSR-${coreInfo.version}\\my-fsr`);
  }
});

// Hardware Diagnostics Tab
async function loadSystemInfo() {
  try {
    const res = await fetch('/api/system/info');
    const info = await res.json();
    const container = document.getElementById('diagnostics-gpus-list');
    container.innerHTML = '';
    if (info.gpus && info.gpus.length > 0) {
      for (const gpu of info.gpus) {
        const item = document.createElement('div');
        item.className = 'status-row';
        item.innerHTML = `
          <div class="status-label">
            <span class="dot done"></span>
            <strong>${escapeHtml(gpu.name)}</strong>
            <span class="sub">Driver: ${gpu.driver || 'N/A'}</span>
          </div>
          <div class="status-val">${gpu.ramMB ? `${gpu.ramMB} MB VRAM` : 'Integrated / Dynamic'}</div>
        `;
        container.appendChild(item);
      }
    } else {
      container.innerHTML = '<p>No GPU details returned.</p>';
    }
  } catch (e) {}
}

async function loadSidebarGpu() {
  try {
    const res = await fetch('/api/system/info');
    const info = await res.json();
    const gpuText = document.getElementById('sidebar-gpu-text');
    if (info.gpus && info.gpus.length > 0) {
      const amdGpu = info.gpus.find(g => g.name.toLowerCase().includes('amd') || g.name.toLowerCase().includes('radeon'));
      const active = amdGpu || info.gpus[0];
      gpuText.textContent = active.name;
    }
  } catch (e) {}
}

// Add Custom Game Directory
document.getElementById('btn-add-game').addEventListener('click', () => {
  const p = prompt('Enter the absolute path to your game folder (e.g. D:\\Games\\MyGame):');
  if (p && p.trim()) {
    addCustomFolder(p.trim());
  }
});

document.getElementById('btn-save-custom-folder').addEventListener('click', () => {
  const input = document.getElementById('custom-folder-input');
  if (input.value.trim()) {
    addCustomFolder(input.value.trim());
    input.value = '';
  }
});

async function addCustomFolder(folderPath) {
  try {
    const res = await fetch('/api/games/add-custom', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folderPath })
    });
    const data = await res.json();
    if (data.success) {
      showToast('Game folder added successfully!', 'success');
      await loadGames();
    }
  } catch (err) {
    showToast('Failed to add folder: ' + err.message, 'error');
  }
}

// Search and Filter Events
searchInput.addEventListener('input', () => {
  clearSearchBtn.style.display = searchInput.value ? 'block' : 'none';
  renderGames();
});

clearSearchBtn.addEventListener('click', () => {
  searchInput.value = '';
  clearSearchBtn.style.display = 'none';
  renderGames();
});

filterLauncher.addEventListener('change', renderGames);
filterStatus.addEventListener('change', renderGames);
sortSelect.addEventListener('change', renderGames);

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Initial Initialization
window.addEventListener('DOMContentLoaded', () => {
  updateVersionTag();
  loadGames();
  checkCoreStatus();
  loadSidebarGpu();
});
