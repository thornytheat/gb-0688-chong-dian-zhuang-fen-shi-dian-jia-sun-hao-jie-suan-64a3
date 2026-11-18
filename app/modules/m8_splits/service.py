import hashlib,json
from datetime import datetime,timezone
from app import store
from app.config import DEFAULTS,RULE_VERSION
from app.errors import DomainError
from app.normalize import number,instant,serial
from app.reasons import rejected
from app.modules.m1_intake.rules import receive
from app.modules.m2_tariffs.rules import normalize,dedup
from .rules import parse_spec,inherit
def _from_text(text,max_hours):
    ctx=receive(text.encode("utf-8"));quarantine=list(ctx["quarantine"]);good=[]
    for row in ctx["records"]:
        try:good.append(normalize(row,max_hours))
        except DomainError as exc:quarantine.append(rejected(row,exc.code,exc.message))
    good,bad=dedup(good);quarantine.extend(bad)
    return good,quarantine,hashlib.sha256(text.encode("utf-8")).hexdigest(),ctx["input_count"]
def _from_run(run_id):
    result=store.fetch(run_id);records=[]
    for row in result.get("records",[]):
        records.append({"id":row["id"],"station":row["station"],"order":row.get("order",""),"start":instant(row["start"]),"end":instant(row["end"]),
                        "energy":number(row["energy"]),"unit":"kWh","bill":number(row["bill"]),"version":int(row["version"]),"kind":row["kind"]})
    return records,[],result["manifest"]["sha256"],len(records)
def execute(text=None,run_id=None,params=None):
    if not isinstance(params,(dict,type(None))):raise DomainError("PARAMS","参数必须是对象")
    actual={**DEFAULTS,**(params or {})};spec=parse_spec(actual)
    loss_rate=number(actual["loss_rate"]);max_hours=number(actual["max_hours"])
    if loss_rate<0 or max_hours<=0 or max_hours>168:raise DomainError("RANGE","结算参数无效")
    if (text is None)==(run_id is None):raise DomainError("PARAMS","数据只能来自CSV或批次之一")
    if run_id is not None:
        if not isinstance(run_id,str):raise DomainError("PARAMS","批次号必须为字符串")
        records,quarantine,digest,total=_from_run(run_id);source="run"
    else:
        if not isinstance(text,str):raise DomainError("TEXT","数据必须为文本")
        records,quarantine,digest,total=_from_text(text,max_hours);source="csv"
    if spec["basis_run"]:store.fetch(spec["basis_run"])
    zones,conservation=inherit(records,spec,loss_rate)
    if len(records)+len(quarantine)!=total:raise DomainError("INCOMPLETE","计量行数不守恒")
    key=hashlib.sha256((digest+spec["station"]+spec["day"].isoformat()+json.dumps(spec["zones"],sort_keys=True,ensure_ascii=False)+RULE_VERSION).encode()).hexdigest()
    result={"split_id":key[:20],"station":spec["station"],"day":spec["day"].isoformat(),"zones":zones,"conservation":conservation,
            "quarantine":quarantine,"input_count":total,"retained":len(records),"isolated":len(quarantine),
            "basis":{"sha256":digest,"rules":RULE_VERSION,"source":source,"run_id":run_id or spec["basis_run"],"params":{"loss_rate":str(loss_rate)}},
            "settleable":all(z["loss_state"]=="通过" for z in zones),"state":"生效","version":1,
            "created":datetime.now(timezone.utc).isoformat()}
    return store.save_split(serial(result))
