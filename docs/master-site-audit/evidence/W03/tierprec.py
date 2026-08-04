import json,sys,statistics,collections
sys.path.insert(0,'/home/user/riskittogetthebrisket')
from src.canonical.player_valuation import detect_tiers
S='/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad'
d=json.load(open(S+'/data_full.json'))
ranked=[r for r in d['playersArray'] if r.get('canonicalConsensusRank')]
ranked.sort(key=lambda r:r['canonicalConsensusRank'])
series=[-float(r['rankDerivedValue']) for r in ranked]
ids=[r['canonicalName'] for r in ranked]
tids,gaps,scores,bounds=detect_tiers(series,ids)
print('tiers',len(set(tids)),'rows',len(ranked))
bg=sorted(bounds,key=lambda b:b.raw_gap)
print('SMALLEST tier boundaries (raw value gap on the 0-9999 scale):')
for b in bg[:8]:
    print(f'  {b.player_above} -> {b.player_below}: gap={b.raw_gap} score={b.gap_score:.2f}')
# For each boundary, compare the gap to the two rows' own sourceSpread
byname={r['canonicalName']:r for r in ranked}
worse=0; tot=0; ex=[]
for b in bounds:
    a=byname.get(b.player_above); c=byname.get(b.player_below)
    if not a or not c: continue
    sa=a.get('sourceSpread'); sc=c.get('sourceSpread')
    if sa is None or sc is None: continue
    tot+=1
    m=max(sa,sc)
    if b.raw_gap < m:
        worse+=1
        if len(ex)<6: ex.append((b.player_above,b.player_below,b.raw_gap,round(sa,1),round(sc,1)))
print(f'\nboundaries whose value gap is SMALLER than the larger of the two rows own sourceSpread: {worse}/{tot} = {100*worse/tot:.1f}%')
for e in ex: print('  ',e)
gapsn=[b.raw_gap for b in bounds]
print('boundary gap: min',min(gapsn),'median',statistics.median(gapsn),'max',max(gapsn))
ss=[r.get('sourceSpread') for r in ranked if r.get('sourceSpread') is not None]
print('sourceSpread over ranked rows: median',round(statistics.median(ss),1),'p90',round(sorted(ss)[int(.9*len(ss))],1))
