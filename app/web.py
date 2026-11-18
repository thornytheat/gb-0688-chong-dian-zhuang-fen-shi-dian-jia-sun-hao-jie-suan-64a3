import json
from flask import render_template,request
from app import store
from app.pipeline import run
from app.config import TITLE,MODULES,STAGES,COLUMNS,SAMPLES,DEFAULTS
def view(stage):
    if stage==8: return splits()
    if not 1<=stage<=7: return "页面不存在",404
    run_id=request.args.get("run")
    result=store.fetch(run_id) if run_id else run()
    sample=(SAMPLES/"dirty.csv").read_text(encoding="utf-8-sig")
    data=result["stages"][stage-1]
    return render_template(f"m{stage}.html",title=TITLE,modules=MODULES,stage=stage,result=result,data=data,
                           sample=sample,defaults=DEFAULTS,columns=COLUMNS,history=store.history())
def splits():
    split_id=request.args.get("split")
    detail=store.fetch_split(split_id) if split_id else None
    sample=(SAMPLES/"split.csv").read_text(encoding="utf-8-sig")
    spec={"split":{"station":"站甲","day":"2026-11-17","zones":[{"name":"站甲·东","meter":"M0A"},{"name":"站甲·西","meter":"M0B"}]},
          "loss_rate":DEFAULTS["loss_rate"]}
    return render_template("m8.html",title=TITLE,modules=MODULES,stage=8,detail=detail,splits=store.splits_history(),
                           sample=sample,sample_params=json.dumps(spec,ensure_ascii=False,indent=2))
