"""Round-6 refit (2026-11-22): from a params file, no restarts, the far-off term on (OK'd trades held within +50 points), calls weighted, the rules Oliver set held at their values. usage: faab_refit_far.py OUT W_FAROFF W_CALLS POLISH START FAR_AT HELD_FROM"""
import sys, os, json; sys.path[:0]=["lib","scripts"]
import pandas as pd
import faab_value as SV
from lotg_support import faab_value as F
out, W, WC, pol, start, at = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5], float(sys.argv[6])
F.W_FAROFF=W; F.W_CALLS=WC; F.FAR_AT=at; F.FAR_OK_RISE=float(os.environ.get("FAR_OK_RISE", F.FAR_OK_RISE))
head=json.load(open(sys.argv[7])); p0=F.load_params(start)
HOLD={"rb_old_hi","overtaken","r1_wr","rookie_r1","lag_cap","boom_week","te_soft","fresh_start","qb_opening","draft_comp","wr_hi","old_cliff","rb_hold","soph_fall","flop_r1","rb_role","comp_young"}
for k in HOLD: p0[k]=head[k]
for k in HOLD: F.BOUNDS.pop(k, None)
ev=F.Evidence.load(os.environ["FDATA"]) if os.environ.get("FDATA") else F.Evidence.load(); ref=pd.read_csv(SV.REF).set_index('name').V; obj=F.objective(ev,ref,SV._vote_term(ev))
d=obj(p0,True); print('start', {k:round(v,4) for k,v in d.items() if k!='tests'}, flush=True)
p=F.fit(obj,[p0],restarts=0,passes=1,polish=pol,log=lambda m: print(m, flush=True))
json.dump(p,open(out,'w'),indent=1)
d=obj(p,True); print('end', {k:round(v,4) for k,v in d.items() if k!='tests'}, [n for n,x in d['tests'] if x>0], flush=True)
z=[k for k in p if head.get(k,0)!=0 and p[k]==0]; print('zeroed', z)
