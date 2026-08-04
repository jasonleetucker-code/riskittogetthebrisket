import json,collections
S='/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad'
d=json.load(open(S+'/data_full.json')); pa=d['playersArray']
pools=collections.Counter()
for r in pa:
    for k in (r.get('sourceRanks') or {}): pools[k]+=1
RET={'ktcSfTep'}
flip=collections.Counter(); ex=[]
tested=0
for r in pa:
    if not r.get('canonicalConsensusRank'): continue
    esr=r.get('effectiveSourceRanks') or {}
    meta=r.get('sourceRankMeta') or {}
    ret=[]; con=[]
    for k,v in esr.items():
        raw=(meta.get(k) or {}).get('rawRank') or v
        p=pools.get(k)
        if not p: continue
        pct=float(raw)/p
        (ret if k in RET else con).append(pct)
    if not ret or not con: continue
    tested+=1
    rm=sum(ret)/len(ret); cm=sum(con)/len(con)
    nd = 'retail_premium' if cm>rm else ('consensus_premium' if cm<rm else 'none')
    od = r.get('marketGapDirection')
    flip[(od,nd)]+=1
    if od!=nd and len(ex)<10:
        ex.append((r['displayName'],r['canonicalConsensusRank'],od,nd,round(r.get('marketGapMagnitude') or 0,1),round(rm,3),round(cm,3)))
print('rows tested',tested)
print('ordinal-gap direction  ->  pool-normalized direction:')
for k,v in sorted(flip.items(), key=lambda t:-t[1]): print('  ',k,v)
disagree=sum(v for k,v in flip.items() if k[0]!=k[1])
print('DIRECTION FLIPS when depth-normalized:',disagree,f'{100*disagree/tested:.1f}%')
for e in ex: print('  ',e)
