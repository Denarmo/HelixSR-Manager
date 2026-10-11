#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""Roll U5's four equivalent family blocks with uniform A/B base selection."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import argparse,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('kernel_dir',type=Path);p.add_argument('--name',choices=('u5','u9'),default='u5');a=p.parse_args();f=a.kernel_dir/(a.name+'_body.h');s=f.read_text()
block_count = 4 if a.name == 'u5' else 2
step_a = 4096 if a.name == 'u5' else 2112
for stage,count in ([(0,64),(1,32)] if a.name == 'u5' else [(0,128)]):
 start=s.index('FAM_API void family_seg'+str(stage)+'(');next_start=s.index('\nFAM_API void family_seg1(',start) if stage==0 and a.name == 'u5' else s.index('\nvoid '+a.name+'_body(',start)
 part=s[start:next_start];first=part.index('  const famu4 ');head=part[:first];body=part[first:];blocks=[];begin=0;depth=0;updates=0
 # Split only after a complete top-level statement enclosing the last update.
 tokens=re.finditer(r'acc\[\d+\] = d;|[{}]',body)
 for token in tokens:
  t=token.group()
  if t=='{':depth+=1
  elif t=='}':
   depth-=1
   if updates==count and depth==0:
    blocks.append(body[begin:token.end()].strip());begin=token.end();updates=0
  else:updates+=1
 assert len(blocks)==block_count,(stage,len(blocks))
 canonical=[]
 for q,block in enumerate(blocks):
  if stage==0:
   block=re.sub(r'pB'+str(q)+r'_', 'pBq_',block)
   block=re.sub(r'(?:fam_act_row|fam_row)\((pA0_\d+) \+ (\d+)u\)',lambda m:('fam_act_row(' if a.name == 'u5' else 'fam_row(')+m[1]+' + '+str(int(m[2])-step_a*q)+'u + q * '+str(step_a)+'u)',block)
  else:
   block=re.sub(r'pA'+str(q+1)+r'_', 'pAq_',block);block=re.sub(r'pB'+str(q)+r'_', 'pBq_',block)
  names={}
  def rename(m):
   key=m[0]
   if key not in names:names[key]='row'+str(len(names))
   return names[key]
  block=re.sub(r'\b[ab]\d+(?=_)',rename,block)
  canonical.append(block)
 assert all(b==canonical[0] for b in canonical),(stage,'blocks differ')
 signature=head[:head.index('  const uint lane')]
 inner='  const uint lane = px_lane();\n  const uint g = lane >> 2, t = lane & 3u;\n'
 if stage==0:
  for i in range(4):inner+=f'  const uint pA0_{i} = fam_perm(bA0, {8*i}u + g);\n'
 inner+=f'  PX_LOOP\n  for (uint q = 0; q < ({block_count}u + px_rtzero()); ++q) {{\n'
 inner+=('  uint bBq = q == 0u ? bB0 : (q == 1u ? bB1 : (q == 2u ? bB2 : bB3));\n' if block_count == 4 else '  uint bBq = q == 0u ? bB0 : bB1;\n')
 if stage==1:
  inner+='  uint bAq = q == 0u ? bA1 : (q == 1u ? bA2 : (q == 2u ? bA3 : bA4));\n'
  for i in range(4):inner+=f'  const uint pAq_{i} = fam_perm(bAq, {8*i}u + g);\n'
 for i in range(4):
  for o in range(2):inner+=f'  const uint pBq_{i}_{o} = fam_perm(bBq, {8*i}u + 2u * t + {o}u);\n'
 replacement=signature+inner+canonical[0]+'\n  }\n}\n'
 s=s[:start]+replacement+s[next_start:]
f.write_text(s)
print(a.name.upper()+'_block_equivalence=PROVEN')
