#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""Port native joint-fragment MMA designs into the shared HLSL/CPU body."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import argparse,re
from pathlib import Path
from kernels import K
import ptx2hlsl as PX
import samplers
p=argparse.ArgumentParser();p.add_argument('name',choices=['k7','k5','k5f','k5n','u4']);p.add_argument('out',type=Path)
p.add_argument('--relaxed-fma32', action='store_true', help='avoid transitive precise on gfx1013 unfused FP32 FMA')
p.add_argument('--mul-round', action='store_true', help='retain multiplication barriers, omit half add/FMA barriers')
p.add_argument('--wave', type=int, choices=(32,64), default=32)
a=p.parse_args()
k8=a.name=='k7';pk=a.name in ('k5','k5f','k5n');sizes=[4] if k8 else [4,6]
def helper(n):
 A=2 if k8 else 4;B=1 if k8 else 2
 args=[f'INOUT(uint) d{i}' for i in range(2*n)]+[f'uint a{i}' for i in range(A)]+[f'uint b{c}_{h}' for c in range(n) for h in range(B)]
 out=[f'void compact_{n}('+', '.join(args)+') {','uint t=px_lane() & 3u;']
 if pk:
  out += [f'PXH2 p{i}=px_h2z(px_u2h2(0u));' for i in range(4*n)]
 else:
  out += [f'float v{4*c+j}=px_h2f(d{2*c+j//2} >> {(j&1)*16}u);' for c in range(n) for j in range(4)]
 pairs=7 if pk else (4 if k8 else 8)
 out += ['PX_LOOP',f'for(uint step=0;step<({pairs}u+px_rtzero());++step) {{','uint tp=(t+step)&3u, src=t*8u+tp;']
 up='a0' if k8 else '(step < 4u ? a0 : a2)';down='a1' if k8 else '(step < 4u ? a1 : a3)'
 out += [f'PXH2 upper=px_u2h2(px_qrd({up},tp)), lower=px_u2h2(px_qrd({down},tp));']
 for c in range(n):
  b=f'b{c}_0' if k8 else f'(step < 4u ? b{c}_0 : b{c}_1)'
  out += [f'PXH2 l{c}=px_u2h2(px_rd({b},src)), r{c}=px_u2h2(px_rd({b},src+4u));']
 if pk:
  for c in range(n):
   for j in range(4):out += [f'p{4*c+j}=px_h2fma({"upper" if j<2 else "lower"}, {"l" if j%2==0 else "r"}{c}, p{4*c+j});']
 else:
  for half in ['lo','hi']:
   for c in range(n):
    for j in range(4):out += [f'v{4*c+j}=px_h2{half}({"upper" if j<2 else "lower"})*px_h2{half}({"l" if j%2==0 else "r"}{c})+v{4*c+j};']
 out += ['}']
 if pk:
  out += ['uint tp=(t+3u)&3u, src=t*8u+tp;','PXH2 upper=px_u2h2(px_qrd(a2,tp)), lower=px_u2h2(px_qrd(a3,tp));']
  for c in range(n):out += [f'PXH2 l{c}=px_u2h2(px_rd(b{c}_1,src)), r{c}=px_u2h2(px_rd(b{c}_1,src+4u));']
  for c in range(n):
   for j in range(4):
    i=4*c+j;out += [f'float v{i}=px_h2f(d{2*c+j//2} >> {(j&1)*16}u)+px_h2lo(p{i});',f'v{i}=v{i}+px_h2hi(p{i});']
  for half in ['lo','hi']:
   for c in range(n):
    for j in range(4):out += [f'v{4*c+j}=px_h2{half}({"upper" if j<2 else "lower"})*px_h2{half}({"l" if j%2==0 else "r"}{c})+v{4*c+j};']
 out += [f'd{i}=px_f2h(v{2*i})|(px_f2h(v{2*i+1})<<16);' for i in range(2*n)]+['}']
 return '\n'.join(out)+'\n'
prefix='// Native joint fragment scheduling; same per-output product and rounding order.\n'+''.join(helper(n) for n in sizes)
class Compact(PX.Tx):
 def __init__(self):
  k=K[a.name];super().__init__(k['ptx'],a.name,k['block'],mma=PX.parse_mma(k['installed']),two=PX.parse_two('all',128),fast=False)
  self.chain_regs={};self.group_end={};self.covered=set();pending=[]
  def emit(pcs):
   assert len(pcs) in sizes
   assert all(self.ins[i]['op'].startswith('mma') for i in range(pcs[0],pcs[-1]+1))
   operands=[[re.findall(r'%\w+',operand) for operand in self.ins[i]['ops']] for i in pcs]
   assert all(len(o[1])==(2 if k8 else 4) and len(o[2])==(1 if k8 else 2) and o[0]==o[3] for o in operands)
   assert all(o[1]==operands[0][1] for o in operands)
   dst=[r for o in operands for r in o[0]];inputs=operands[0][1]+[r for o in operands for r in o[2]]
   assert len(set(dst))==2*len(pcs) and not set(dst)&set(inputs)
   self.group_end[pcs[-1]]='compact_'+str(len(pcs))+'('+', '.join(self.vname(r) for r in dst+inputs)+');';self.covered.update(pcs)
  for i in self.k.mma_sites:
   if pending and (self.ins[i]['ops'][1]!=self.ins[pending[0]]['ops'][1] or (k8 and len(pending)==4)):
    emit(pending);pending=[]
   pending.append(i)
  if pending:emit(pending)
 def tr(self,i,x):
  if i in self.covered:return [self.group_end[i]] if i in self.group_end else []
  return super().tr(i,x)
a.out.mkdir(exist_ok=True,parents=True);tx=Compact()
for spec in filter(None, samplers.spec(a.name).split(',')):
 off, filt, au, av = map(int, spec.split(':'))
 tx.samplers[off] = (filt, au, av)
PX.write(tx,a.out,wave=a.wave)
flags=['PX_FMA32_UNFUSED','PX_HALF_UNPACK','PX_HALF_ROUND_BARRIER']
if a.relaxed_fma32:flags.append('PX_FMA32_RELAXED')
if a.mul_round:flags+=['PX_HALF_ADD_NO_BARRIER','PX_HALF_FMA_NO_BARRIER']
f=a.out/(a.name+'_body.h');f.write_text(prefix+f.read_text());f=a.out/(a.name+'_cfg.h');f.write_text(''.join('#define '+flag+' 1\n' for flag in flags)+f.read_text())
print('joint_MMA_groups='+str(len(tx.group_end)))
