
"""V4.2 local concurrency smoke (no paid model)."""
from __future__ import annotations
import os, time, statistics
from concurrent.futures import ThreadPoolExecutor
import httpx

BASE=os.environ.get("PAPERLENS_API_BASE","http://127.0.0.1:8000/api")
EMAIL=os.environ.get("QA_EMAIL","qa@paperlens.ai"); PASSWORD=os.environ.get("QA_PASSWORD","QaResearch123!")

def one(index: int) -> tuple[int,float,str]:
    started=time.time()
    with httpx.Client(timeout=180) as c:
        login=c.post(BASE+"/auth/login",json={"email":EMAIL,"password":PASSWORD})
        h={"Authorization":"Bearer "+login.json()["access_token"]}
        with c.stream("POST",BASE+"/chat/stream",headers=h,json={"message":f"总结资料库中的主要研究主题（并发测试 {index}）","mode":"quick","scope_type":"all"}) as r:
            code=r.status_code
            for _ in r.iter_lines():
                pass
    return code, time.time()-started, ""

def main():
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows=list(pool.map(one, range(6)))
    times=[r[1] for r in rows]
    print("requests",len(rows),"ok",sum(1 for r in rows if r[0]==200),"failed",sum(1 for r in rows if r[0]!=200))
    print("avg_ms",round(statistics.mean(times)*1000),"p95_ms",round(sorted(times)[int(len(times)*0.95)-1]*1000),"max_ms",round(max(times)*1000))
    for r in rows: print(r[0],round(r[1],2))

if __name__=="__main__": main()
