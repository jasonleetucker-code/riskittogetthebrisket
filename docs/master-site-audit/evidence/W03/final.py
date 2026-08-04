import json,collections,statistics
S='/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad'
d=json.load(open(S+'/data_full.json')); pa=d['playersArray']
ranked=[r for r in pa if r.get('canonicalConsensusRank') and r.get('assetClass')!='pick']
# A: legacy 30/80 rule vs live percentile rule
def legacy(n,srs):
    if n>=2 and srs is not None:
        if srs<=30: return 'high'
        if srs<=80: return 'medium'
    return 'low' if n>=1 else 'none'
diff=collections.Counter()
for r in ranked:
    n=len(r.get('effectiveSourceRanks') or {}); srs=r.get('sourceRankSpread')
    lg=legacy(n,srs); got=r['confidenceBucket']
    if lg!=got: diff[(got,lg)]+=1
tot=len(ranked); s=sum(diff.values())
print(f'A) rows where the LEGACY 30/80 rule would give a different bucket: {s}/{tot} = {100*s/tot:.1f}%', dict(diff))
# B: value-space dispersion inside 'high'
hi=[r for r in ranked if r['confidenceBucket']=='high' and r.get('hillValueSpread') and r.get('rankDerivedValue')]
rel=[r['hillValueSpread']/r['rankDerivedValue'] for r in hi]
over=[r for r in hi if r['hillValueSpread']/r['rankDerivedValue']>0.30]
print(f"B) 'high' rows: {len(hi)}; with hillValueSpread/value > 30%: {len(over)} ({100*len(over)/len(hi):.1f}%)")
print('   median rel disp by bucket:',{b:round(statistics.median([r['hillValueSpread']/r['rankDerivedValue'] for r in ranked if r['confidenceBucket']==b and r.get('hillValueSpread') and r.get('rankDerivedValue')]),4) for b in ('high','medium','low')})
print('   worst high rows:',[(r['displayName'],r['rankDerivedValue'],round(r['hillValueSpread'],1),round(r['hillValueSpread']/r['rankDerivedValue'],3),len(r.get('effectiveSourceRanks') or {})) for r in sorted(over,key=lambda x:-x['hillValueSpread']/x['rankDerivedValue'])[:5]])
# C: offense-only marketGap flip rate
pools=collections.Counter()
for r in pa:
    for k in (r.get('sourceRanks') or {}): pools[k]+=1
def flip(rows):
    f=t=0
    for r in rows:
        esr=r.get('effectiveSourceRanks') or {}; meta=r.get('sourceRankMeta') or {}
        ret=[];con=[]
        for k,v in esr.items():
            raw=(meta.get(k) or {}).get('rawRank') or v; p=pools.get(k)
            if not p: continue
            (ret if k=='ktcSfTep' else con).append(raw/p)
        if not ret or not con: continue
        t+=1
        nd='retail_premium' if sum(con)/len(con)>sum(ret)/len(ret) else 'consensus_premium'
        if nd!=r.get('marketGapDirection'): f+=1
    return f,t
for lab,cls in (('offense','offense'),('idp','idp'),('pick','pick')):
    rows=[r for r in pa if r.get('canonicalConsensusRank') and r.get('assetClass')==cls]
    f,t=flip(rows)
    print(f'C) {lab}: {f}/{t} flip = {100*f/t if t else 0:.1f}%')
