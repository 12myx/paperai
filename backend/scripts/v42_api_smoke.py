
"""Small final API smoke for V4.2 (the old 88-step temp script was removed by temp cleanup)."""
from __future__ import annotations
import json, os
import httpx

BASE=os.environ.get("PAPERLENS_API_BASE","http://127.0.0.1:8000/api")
EMAIL=os.environ.get("QA_EMAIL","qa@paperlens.ai"); PASSWORD=os.environ.get("QA_PASSWORD","QaResearch123!")
checks=[]

def check(name, condition, detail=""):
    checks.append((name, bool(condition), detail))

def main():
    with httpx.Client(timeout=180) as c:
        check("health", c.get(BASE+"/health").status_code==200)
        login=c.post(BASE+"/auth/login",json={"email":EMAIL,"password":PASSWORD}); check("login",login.status_code==200)
        h={"Authorization":"Bearer "+login.json()["access_token"]}
        for name,path in [("settings","/settings"),("papers","/papers?limit=5"),("knowledge","/knowledge?limit=5"),("figures","/figures?limit=5"),("artifacts","/artifacts?limit=5"),("projects","/projects"),("evidence","/evidence?limit=5"),("stats","/library/stats")]:
            r=c.get(BASE+path,headers=h); check(name,r.status_code==200)
        papers=c.get(BASE+"/papers?limit=5",headers=h).json().get("items",[])
        events=[]
        with c.stream("POST",BASE+"/chat/stream",headers=h,json={"message":"总结资料库的主要主题。","mode":"quick","scope_type":"all"}) as r:
            check("chat_stream",r.status_code==200)
            for line in r.iter_lines():
                if line.startswith("data: "):
                    try: events.append(json.loads(line[6:]))
                    except json.JSONDecodeError: pass
        done=next((e for e in events if e.get("type")=="done"),{})
        check("chat_done",bool(done.get("run_id")))
        if done.get("run_id"):
            usage=c.get(BASE+f"/agent/runs/{done['run_id']}/resources",headers=h); check("usage_endpoint",usage.status_code==200)
        if papers:
            ev=[]
            with c.stream("POST",BASE+"/chat/stream",headers=h,json={"message":"把这篇论文的核心结论保存到知识库","mode":"quick","scope_type":"papers","scope_ids":[papers[0]["id"]]}) as r:
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        try: ev.append(json.loads(line[6:]))
                        except json.JSONDecodeError: pass
            action=next((e["action"] for e in ev if e.get("type")=="action" and e["action"].get("tool")=="save_knowledge"),None)
            check("action_created",bool(action and action.get("action_id")))
            if action:
                st=c.get(BASE+f"/agent/actions/{action['action_id']}",headers=h); check("action_status",st.status_code==200)
                payload={"tool":action["tool"],"args":action["args"],"action_id":action["action_id"]}
                first=c.post(BASE+"/agent/actions/confirm",headers=h,json=payload); check("action_confirm",first.status_code==200)
                replay=c.post(BASE+"/agent/actions/confirm",headers=h,json=payload); check("action_replay",replay.status_code==400)
    for name,ok,detail in checks: print(("PASS " if ok else "FAIL ")+name,detail)
    print("SUMMARY",sum(1 for _,ok,_ in checks if ok),"/",len(checks))
    return 0 if all(ok for _,ok,_ in checks) else 1

if __name__=="__main__":
    raise SystemExit(main())
