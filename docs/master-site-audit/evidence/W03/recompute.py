import json, collections
S='/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad'
d=json.load(open(S+'/data_full.json'))
pa=d['playersArray']
PH,PM=0.08,0.20
SH,SM=30,80
DB=0.10; SB=0.20; CAP=0.25

def conf(n, srs, ps):
    if n>=2:
        if ps is not None:
            if ps<=PH: return 'high'
            if ps<=PM: return 'medium'
        elif srs is not None:
            if srs<=SH: return 'high'
            if srs<=SM: return 'medium'
    if n>=1: return 'low'
    return 'none'

ranked=[r for r in pa if r.get('canonicalConsensusRank')]
print('rows', len(pa), 'ranked', len(ranked))
total_ranked=min(len(pa),800)
# find actual OVERALL_RANK_LIMIT usage: max rank
print('max rank', max(r['canonicalConsensusRank'] for r in ranked))

mis=collections.Counter(); mis_ex=[]
mis_dis=0; dis_ex=[]
mis_gap=0; gap_ex=[]
mis_spread=0
n_pick=0
for r in ranked:
    ac=r.get('assetClass')
    esr=r.get('effectiveSourceRanks') or {}
    ps=r.get('sourceRankPercentileSpread')
    srs=r.get('sourceRankSpread')
    if ac=='pick':
        n_pick+=1
    else:
        exp=conf(len(esr), srs, ps)
        got=r.get('confidenceBucket')
        if exp!=got:
            mis[(exp,got)]+=1
            if len(mis_ex)<15: mis_ex.append((r['displayName'],len(esr),ps,srs,exp,got,r.get('anomalyFlags')))
    # hasSourceDisagreement
    rank=r['canonicalConsensusRank']
    allowance=min(max(rank/float(total_ranked),0.0),CAP)
    exp_dis = ps is not None and ps > DB+allowance
    if exp_dis != bool(r.get('hasSourceDisagreement')):
        mis_dis+=1
        if len(dis_ex)<8: dis_ex.append((r['displayName'],rank,ps,allowance,exp_dis,r.get('hasSourceDisagreement')))
    # market gap: retail = ktcSfTep? determine
print('CONFIDENCE mismatches by (expected,actual):', dict(mis), 'picks skipped', n_pick)
for e in mis_ex: print('  ',e)
print('rate', sum(mis.values())/max(1,len(ranked)-n_pick))
print('DISAGREEMENT mismatches', mis_dis)
for e in dis_ex: print('  ',e)
