import json, collections, itertools, sys
sys.path.insert(0,'/home/user/riskittogetthebrisket')
from src.api.data_contract import _compute_confidence_bucket, _percentile_rank_spread
S='/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad'
d=json.load(open(S+'/data_full.json'))
pa=d['playersArray']
pools=collections.Counter()
for r in pa:
    for k in (r.get('sourceRanks') or {}): pools[k]+=1
pools=dict(pools)
ORDER={'none':0,'low':1,'medium':2,'high':3}

improved=0; total=0; ex=[]
byN=collections.defaultdict(collections.Counter)
for r in pa:
    if not r.get('canonicalConsensusRank'): continue
    if r.get('assetClass')=='pick': continue
    esr=dict(r.get('effectiveSourceRanks') or {})
    meta=r.get('sourceRankMeta') or {}
    if len(esr)<3: continue
    base=r.get('confidenceBucket')
    byN[len(esr)][base]+=1
    total+=1
    best=base
    bestdrop=None
    # drop exactly ONE source, try all
    for k in list(esr):
        sub={a:b for a,b in esr.items() if a!=k}
        submeta={a:b for a,b in meta.items() if a!=k}
        ps=_percentile_rank_spread(sub,submeta,pools)
        rv=list(sub.values()); srs=float(max(rv)-min(rv)) if len(rv)>=2 else None
        b,_=_compute_confidence_bucket(len(sub), srs, percentile_spread=ps)
        if ORDER[b]>ORDER[best]: best=b; bestdrop=k
    if ORDER[best]>ORDER[base]:
        improved+=1
        if len(ex)<12: ex.append((r['displayName'],len(esr),base,best,bestdrop,r.get('sourceRankPercentileSpread')))
print('rows tested (>=3 eff sources, non-pick, ranked):',total)
print('rows where DROPPING ONE SOURCE RAISES confidence:',improved, round(100*improved/total,1),'%')
for e in ex: print('  ',e)
print()
print('confidence distribution by effective source count:')
for n in sorted(byN):
    c=byN[n]; tot=sum(c.values())
    print(f'  n={n:2d} tot={tot:4d} high={c["high"]:4d} ({100*c["high"]/tot:5.1f}%) medium={c["medium"]:4d} low={c["low"]:4d}')
