import json, math, sys, random
root = sys.argv[1]
def Phi(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def phi(z): return math.exp(-z*z/2)/math.sqrt(2*math.pi)
def trunc_mean_ratio(cv):  # E[max(0,N(1,cv))]
    z=1/cv; return Phi(z)+cv*phi(z)
fb={"QB":0.32,"RB":0.55,"WR":0.60,"TE":0.65,"DL":0.55,"LB":0.45,"DB":0.50}
ev=json.load(open(root+"/docs/league-intelligence/evidence/sim_calibration_v3/evaluation_v3.json",encoding="utf-8"))
out={"truncation":{}, "cvRatio":{}}
for wk in ("week5","week6","week7","week8"):
    f=ev["fits"].get(wk,{}).get("V3")
    if not f: continue
    for pos,c in f["cv"].items():
        out["cvRatio"].setdefault(pos,{})[wk]=c["cv"]
for pos,cv in fb.items():
    out["truncation"][pos]={"fallbackCv":cv,"meanInflationFallback":round(trunc_mean_ratio(cv)-1,4)}
for pos,d in out["cvRatio"].items():
    m=max(d.values())
    out["truncation"].setdefault(pos,{})["meanInflationAtMaxMeasuredCv"]=round(trunc_mean_ratio(m)-1,4)
    out["truncation"][pos]["maxMeasuredV3Cv"]=m
# late-game sd: current sd = cv*mu*f ; increment model sd = cv*mu*sqrt(f)
out["remainingSdRatio_current_over_sqrtf"]={str(f):round(f/math.sqrt(f),3) for f in (0.75,0.5,0.25,0.1)}
# effect on a close live matchup: two teams, each 5 remaining players mean 6 pts at full game, cv .6, leader up L points with f remaining
random.seed(1)
def winp(L,f,mode,n=40000):
    w=0
    for _ in range(n):
        s=0.0
        for side in (1,-1):
            for _ in range(5):
                mu=6*f; sd=max(0.5, (0.6*6*f) if mode=="cur" else 0.6*6*math.sqrt(f))
                s+=side*max(0.0,random.gauss(mu,sd))
        w+= (L+s)>0
    return round(w/n,3)
out["toyLiveWinProb"]={f"L{L}_f{f}":{"current":winp(L,f,"cur"),"sqrtf":winp(L,f,"sq")} for L in (5,10) for f in (0.5,0.25)}
print(json.dumps(out,indent=1))
