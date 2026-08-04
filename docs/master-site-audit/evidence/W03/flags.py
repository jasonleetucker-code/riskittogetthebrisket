import json,sys,collections
sys.path.insert(0,'/home/user/riskittogetthebrisket')
from src.api.data_contract import _compute_anomaly_flags, _disagreement_depth_allowance
S='/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad'
d=json.load(open(S+'/data_full.json'))
pa=d['playersArray']
ranked=[r for r in pa if r.get('canonicalConsensusRank')]
total=min(len(pa),800)
mism=collections.Counter(); ex=[]
for r in ranked:
    a=_disagreement_depth_allowance(r['canonicalConsensusRank']/float(total))
    audit=r.get('sourceAudit') or {}
    exp=_compute_anomaly_flags(
        name=r.get('canonicalName') or r.get('displayName') or '',
        position=r.get('position'), asset_class=r.get('assetClass') or '',
        source_ranks=r.get('effectiveSourceRanks') or {},
        source_meta={}, rank_derived_value=r.get('rankDerivedValue'),
        canonical_sites=r.get('canonicalSiteValues') or {},
        percentile_spread=r.get('sourceRankPercentileSpread'),
        expected_sources=list(audit.get('expectedSources') or []),
        disagreement_allowance=a)
    got=[f for f in (r.get('anomalyFlags') or []) if f not in ('unsupported_position','duplicate_canonical_identity','position_source_contradiction','no_valid_source_values','name_collision_cross_universe')]
    if sorted(exp)!=sorted(got):
        mism[(tuple(sorted(exp)),tuple(sorted(got)))]+=1
        if len(ex)<8: ex.append((r['displayName'],r['canonicalConsensusRank'],r.get('sourceRankPercentileSpread'),round(a,4),exp,got))
print('anomalyFlags mismatches:',sum(mism.values()),'of',len(ranked))
for k,v in mism.items(): print(' ',k,v)
for e in ex: print('  ',e)
