"""CPU-only: derive, from one CTA of a capture run through ptxsim, the LDS row-address tables the fast-1x1 helpers need.

For every MMA execution it records where each A/B fragment register came from (ldmatrix pc + matrix j, or a plain
register for phase-2 A operands) and checks:
  - every ldmatrix address vector = (address vector of a chosen base ldmatrix) + a lane-uniform constant;
  - loop sites: the LDS bytes each ldmatrix read equal the LDS contents at the start of that loop iteration (so a helper
    at the loop header can read the whole stage);
  - the tables are identical in every iteration.
Output: tables/<K>.json  {sites: [{site, chain, kind, A: [[j, off] per (r,h)], B: [[j, off] per h], baseA, baseB}],
                          header_pc, chains, ...}
Usage: trace_frags.py <K> [capture-run-dir]"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import json, re, sys
from pathlib import Path
import numpy as np
import validate as V
S = V.ptxsim
R0 = V.R0


def main(k, run, model=None):
    kern = S.Kernel(V.NAMES[k]['ptx'])
    two = V.sites(json.load(open(Path(__file__).parent / 'two_sites.json'))[k], len(kern.mma_sites))
    reps = sorted((Path(run) / 'replay').iterdir())
    cap = [r for r in reps if r.name.endswith(V.NAMES[k]['kernel'])][0]
    mem, args, launch = S.load_capture(cap)
    cta = S.CTA(kern, mem, args, (0, 0, 0), launch[3:6], two_round=two, grid=launch[:3])
    prov = {}          # reg -> (event id, j)
    events = []        # (pc, addr full-block vector, x, data words per j, iteration)
    snap = {}          # iteration -> smem copy at loop header
    it = [-1]
    # loop header = target of the PTX back-edge (if any)
    back = [(kern.labels[m.group(1)], i) for i, x in enumerate(kern.ins) if x['op'].startswith('bra')
            for m in [re.search(r'(\$\w+)', ' '.join(x['ops']))] if m and kern.labels.get(m.group(1), 1e9) < i]
    assert len(back) <= 1, back
    header = back[0][0] if back else None
    lo, hi = (back[0] if back else (None, None))

    def at_header(c, sel):
        it[0] += 1
        snap[it[0]] = c.smem.copy()
    hooks = {'labels': {header: at_header}} if header is not None else {'labels': {}}
    orig_ld = S.CTA.ldmatrix
    orig_setr = S.CTA.setr

    clock = [0]
    wtime = {}

    def setr(self, name, idx, v, bits=32):
        clock[0] += 1
        wtime[name] = clock[0]
        prov.pop(name, None)
        return orig_setr(self, name, idx, v, bits)

    def ldmatrix(self, ins, idx):
        orig_ld(self, ins, idx)
        regs = re.findall(r'%\w+', ins['ops'][0])
        a = self.addr(ins['ops'][1], idx).astype(np.int64)
        full = np.zeros(self.n, dtype=np.int64)
        full[idx] = a
        pc = kern.ins.index(ins)
        lanes = np.arange(self.n); w = lanes - lanes % 32
        rows = [full[w + 8 * j + (lanes % 32) // 4] + (lanes % 4) * 4 for j in range(len(regs))]
        data = [self.smem[r[:, None] + np.arange(4)].copy() for r in rows]
        clock[0] += 1
        events.append(dict(pc=pc, addr=full, x=len(regs), it=it[0], areg=ins['ops'][1].strip()[1:-1], rows=rows, data=data,
                           t=clock[0], smem=self.smem.copy()))
        for j, r in enumerate(regs):
            prov[r] = (len(events) - 1, j)
    sites = []
    msnap = {}

    def mma(c, site, idx, D, A, B, C):
        msnap[site] = c.smem.copy()
        sites.append(dict(site=site, D=tuple(D), it=it[0], areg_t=max(wtime.get(r, 0) for r in A), A=[prov.get(r, ('reg', r)) for r in A],
                          B=[prov.get(r, ('reg', r)) for r in B], pc=kern.mma_sites[site]))
        return model(c, site, idx, D, A, B, C) if model is not None else None   # UP port: optional candidate numerics
    hooks['mma'] = mma
    S.CTA.ldmatrix, S.CTA.setr = ldmatrix, setr
    try:
        cta.hooks = hooks
        cta.run()
    finally:
        S.CTA.ldmatrix, S.CTA.setr = orig_ld, orig_setr
    n = cta.n
    W = n // 32
    # LDS stability: loop-site ldmatrix data must equal the header snapshot of their iteration
    used = {}
    for s in sites:
        for e in s['A'] + s['B']:
            if e[0] != 'reg':
                used.setdefault(e[0], set()).add(s['site'])
    unstable = []
    in_loop = lambda pc: lo is not None and lo <= pc <= hi
    for ev, ss in used.items():
        e = events[ev]
        sites_in_loop = [s for s in ss if in_loop(kern.mma_sites[s])]
        if not sites_in_loop:
            continue
        # iteration of the consuming MMA = iteration of the site execution; use the first consumer's iteration
        cons_it = min(x['it'] for x in sites if x['site'] in sites_in_loop and (ev in [y[0] for y in x['A'] + x['B']]))
        if cons_it < 0:
            unstable.append((ev, 'consumed before first header'))
            continue
        sm = snap[cons_it]
        for j in range(e['x']):
            if not (sm[e['rows'][j][:, None] + np.arange(4)] == e['data'][j]).all():
                unstable.append((ev, f'pc {e["pc"]} matrix {j}: LDS changed between iteration {cons_it} header and the read'))
    # straight-line groups: helper placed after the last site of the group; its LDS must still hold every row read
    executed = {x['site'] for x in sites}   # UP port: sites on paths this capture never takes stay original MMA code

    def groups():
        p1 = [x for x in range(len(kern.mma_sites)) if in_loop(kern.mma_sites[x]) and x in executed]
        rest = [x for x in range(len(kern.mma_sites)) if x not in p1 and x in executed]
        out = []
        if not p1:
            # no loop: phase 1 = sites whose A comes from ldmatrix, phase 2 = sites whose A comes from registers
            p1 = sorted({x['site'] for x in sites if x['A'][0][0] != 'reg'})
            rest = [x for x in rest if x not in p1]
        out.append(p1)
        if rest:
            out.append(rest)
        return out
    for g in groups():
        last = max(g)
        sm = msnap[last]
        for x in sites:
            if x['site'] in g:
                for e_ in x['A'] + x['B']:
                    if e_[0] == 'reg':
                        continue
                    e = events[e_[0]]
                    for j in range(e['x']):
                        if not (sm[e['rows'][j][:, None] + np.arange(4)] == e['data'][j]).all():
                            unstable.append((e_[0], f'pc {e["pc"]}: LDS changed before site {last}'))
    # maximal segments of the straight-line phase: consecutive sites whose LDS rows are all still intact at the
    # segment's last site (the helper for a segment is placed right after that site)
    def stable(seg):
        """Placement = right after the latest ldmatrix event feeding the segment; every row it reads must be intact
        there, and every register A operand must already be written. Returns the placement event or None."""
        evs = [e_[0] for x in sites if x['site'] in seg for e_ in x['A'] + x['B'] if e_[0] != 'reg']
        if not evs:
            return None
        pe = max(evs, key=lambda e: events[e]['t'])
        sm = events[pe]['smem']
        for ev in set(evs):
            e = events[ev]
            for j in range(e['x']):
                if not (sm[e['rows'][j][:, None] + np.arange(4)] == e['data'][j]).all():
                    return None
        if any(x['areg_t'] > events[pe]['t'] for x in sites if x['site'] in seg):
            return None
        return pe
    segs = []
    for g in groups():
        if lo is not None and in_loop(kern.mma_sites[g[0]]):
            segs.append(dict(kind='loop', sites=g))
            continue
        cur = []
        for x in g:
            if cur and stable(cur + [x]) is None:
                pe = stable(cur)
                segs.append(dict(kind='line', sites=cur, after_ldm_pc=events[pe]['pc'] if pe is not None else None)); cur = []
            cur.append(x)
        pe = stable(cur)
        segs.append(dict(kind='line', sites=cur, after_ldm_pc=events[pe]['pc'] if pe is not None else None))
    unstable = [u for u in unstable if not u[1].startswith('pc ') or 'LDS changed before' not in u[1]] + \
               [('segment', s_['sites'][0], s_['sites'][-1]) for s_ in segs if s_['kind'] == 'line' and s_['after_ldm_pc'] is None]
    globals()['_segs'] = segs
    return kern, sites, events, header, (lo, hi), unstable, n


def tables(k, run=R0):
    kern, sites, events, header, loop, unstable, n = main(k, run)
    lanes = np.arange(n)
    # base ldmatrix events: per operand kind, the address of the first event feeding site 0 (A) / (B)
    first_it = min(s['it'] for s in sites)
    def addr32(e):        # per-warp lane addresses (all warps must agree on the offset pattern relative to base)
        return events[e]['addr'].reshape(-1, 32)
    def _unused(e, base):
        d = addr32(e) - addr32(base)
        x = events[e]['x']
        d = d[:, :8 * x]
        assert (d == d[0, 0]).all(), ('non-uniform ldmatrix offset', events[e]['pc'], events[base]['pc'])
        return int(d[0, 0])
    out = dict(k=k, header_pc=header, loop=loop, sites=[], unstable=unstable, segments=globals()['_segs'])
    # pick the iteration-0 executions (or the only execution for straight-line sites)
    by_site = {}
    for s in sites:
        by_site.setdefault(s['site'], []).append(s)
    bases = {'A': [], 'B': []}
    def place(kind, e):
        for bi, bse in enumerate(bases[kind]):
            d = addr32(e) - addr32(bse)
            d = d[:, :8 * events[e]['x']]
            if (d == d[0, 0]).all():
                return bi, int(d[0, 0])
        bases[kind].append(e)
        return len(bases[kind]) - 1, 0
    for site in sorted(by_site):
        ex = by_site[site]
        rows = []
        for s in ex:
            ra = [('reg', a[1]) if a[0] == 'reg' else ('lds', a[1], *place('A', a[0])) for a in s['A']]
            rb = [('reg', b[1]) if b[0] == 'reg' else ('lds', b[1], *place('B', b[0])) for b in s['B']]
            rows.append((ra, rb))
        same = all(r == rows[0] for r in rows)
        out['sites'].append(dict(site=site, chain=list(ex[0]['D']), execs=len(ex), A=rows[0][0], B=rows[0][1],
                                 iterations_agree=same))
    out['basesA'] = [dict(pc=events[e]['pc'], areg=events[e]['areg'], it=events[e]['it']) for e in bases['A']]
    out['basesB'] = [dict(pc=events[e]['pc'], areg=events[e]['areg'], it=events[e]['it']) for e in bases['B']]
    # UP port: a loop segment whose base addresses come from an ldmatrix INSIDE the loop cannot run at the loop header
    # (on iteration 0 that base alloca is not yet written -> undefined address -> the optimizer deletes the loop as UB).
    # Place it right after the latest in-loop base ldmatrix instead, and verify per iteration that every row the
    # segment reads is still intact in LDS at that point.
    by_pc = {}
    for i, e in enumerate(events):
        by_pc.setdefault(e['pc'], []).append(i)
    for seg in out['segments']:
        if seg['kind'] != 'loop':
            continue
        used = [b for x in out['sites'] if x['site'] in seg['sites'] for a in x['A'] + x['B'] if a[0] == 'lds'
                for b in [('A' if a in x['A'] else 'B', a[2])]]
        inloop = [t_ for kind, gi in set(used) for t_ in [out['basesA' if kind == 'A' else 'basesB'][gi]] if t_['it'] >= 0]
        if not inloop:
            continue
        pc = max(t_['pc'] for t_ in inloop)
        evs = by_pc[pc]
        iters = sorted({s['it'] for s in sites if s['site'] in seg['sites']})
        assert len(evs) == len(iters), ('in-loop base ldmatrix not executed once per iteration', pc, len(evs), len(iters))
        bad = []
        for it_, ev in zip(iters, evs):
            sm = events[ev]['smem']
            for s in sites:
                if s['site'] in seg['sites'] and s['it'] == it_:
                    for e_ in s['A'] + s['B']:
                        if e_[0] == 'reg':
                            continue
                        e = events[e_[0]]
                        for j in range(e['x']):
                            if not (sm[e['rows'][j][:, None] + np.arange(4)] == e['data'][j]).all():
                                bad.append((it_, e['pc']))
        assert not bad, ('rows not intact after in-loop base ldmatrix', pc, bad[:4])
        seg['after_ldm_pc'] = pc
        seg['placement'] = 'after_in_loop_base'
    chains = list(dict.fromkeys(tuple(s['chain']) for s in out['sites']))
    for s in out['sites']:
        s['chain_id'] = chains.index(tuple(s['chain']))
    out['chains'] = [list(c) for c in chains]
    return out


if __name__ == '__main__':
    k = sys.argv[1]
    run = Path(sys.argv[2]) if len(sys.argv) > 2 else R0
    t = tables(k, run)
    od = Path(__file__).parent / 'tables'; od.mkdir(exist_ok=True)
    (od / f'{k}.json').write_text(json.dumps(t, indent=1, default=str) + '\n')
    nreg = sum(1 for s in t['sites'] for a in s['A'] if a[0] == 'reg')
    print(k, 'sites', len(t['sites']), 'chains', len(t['chains']), 'basesA', t['basesA'], 'basesB', t['basesB'],
          'A-from-reg operands', nreg, 'iterations agree', all(s['iterations_agree'] for s in t['sites']),
          'unstable', t['unstable'][:3], 'segments', [(x['kind'], x['sites'][0], x['sites'][-1], x.get('after_ldm_pc')) for x in t['segments']])
