import json,sys,collections,statistics
sys.path.insert(0,'/home/user/riskittogetthebrisket')
from src.api.data_contract import _compute_market_gap,_retail_source_keys
S='/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad'
d=json.load(open(S+'/data_full.json')); pa=d['playersArray']
print('retail keys',_retail_source_keys())
bad=0; ex=[]
for r in pa:
    if not r.get('canonicalConsensusRank'): continue
    dirx,mag=_compute_market_gap(r.get('effectiveSourceRanks') or {})
    if dirx!=r.get('marketGapDirection') or (mag is None)!=(r.get('marketGapMagnitude') is None) or (mag is not None and abs(mag-r['marketGapMagnitude'])>1e-9):
        bad+=1
        if len(ex)<5: ex.append((r['displayName'],dirx,mag,r.get('marketGapDirection'),r.get('marketGapMagnitude')))
print('marketGap mismatches',bad,ex)
# Depth bias test: does effectiveRank == rawRank for offense sources?
diff=collections.Counter(); n=0
for r in pa:
    for k,m in (r.get('sourceRankMeta') or {}).items():
        if m.get('rawRank')!=m.get('effectiveRank'): diff[k]+=1
        n+=1
print('rows where effectiveRank != rawRank, by source:',dict(diff))
# Now: bias. For each ranked offense row, consensus mean rank uses sources whose pools differ.
# Measure systematic direction of marketGapDirection across board depth.
byband=collections.defaultdict(collections.Counter)
for r in pa:
    rk=r.get('canonicalConsensusRank')
    if not rk: continue
    band=(rk-1)//100*100
    byband[band][r.get('marketGapDirection')]+=1
for b in sorted(byband): print(' ranks',b,'-',b+99,dict(byband[b]))
