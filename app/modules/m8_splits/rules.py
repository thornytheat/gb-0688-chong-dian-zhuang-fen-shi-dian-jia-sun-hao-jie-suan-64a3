from datetime import date,datetime,time,timedelta,timezone
from decimal import Decimal as D,ROUND_FLOOR,ROUND_HALF_UP
from app.errors import DomainError
ZONE=timezone(timedelta(hours=8))
def parse_spec(params):
    if not isinstance(params,dict):raise DomainError("PARAMS","参数必须是对象")
    spec=params.get("split")
    if not isinstance(spec,dict):raise DomainError("PARAMS","缺少split拆分参数")
    station=str(spec.get("station") or "").strip()
    if not station:raise DomainError("MISSING","旧站名缺失")
    try:day=date.fromisoformat(str(spec.get("day","")).strip())
    except ValueError:raise DomainError("TIME","拆分日格式应为YYYY-MM-DD")
    zones=spec.get("zones")
    if not isinstance(zones,list) or len(zones)<2:raise DomainError("LIMIT","拆分至少两个运营区")
    names,meters,result=set(),set(),[]
    for zone in zones:
        if not isinstance(zone,dict):raise DomainError("PARAMS","运营区必须是对象")
        name=str(zone.get("name") or "").strip();meter=str(zone.get("meter") or "").strip()
        if not name or not meter:raise DomainError("MISSING","运营区名称或总表号缺失")
        if name==station:raise DomainError("CONFLICT","运营区名不能沿用旧站名")
        if name in names or meter in meters:raise DomainError("DUPLICATE","运营区或总表重复")
        names.add(name);meters.add(meter);result.append({"name":name,"meter":meter})
    basis=spec.get("basis_run")
    if basis is not None and not isinstance(basis,str):raise DomainError("PARAMS","依据批次必须为字符串")
    return {"station":station,"day":day,"zones":result,"basis_run":basis}
def day_bounds(day):
    start=datetime.combine(day,time.min,ZONE);return start,start+timedelta(days=1)
def segments(spec,meters):
    result=[]
    for zone in spec["zones"]:
        meter=meters.get(zone["meter"])
        if meter is None:raise DomainError("ORPHAN",f"总表{zone['meter']}不在旧站计量中")
        result.append({"zone":zone["name"],"meter":zone["meter"],"start":meter["start"],"end":meter["end"],"meter_kwh":meter["energy"],"orders":[]})
    result.sort(key=lambda s:(s["start"],s["meter"]))
    start,end=day_bounds(spec["day"])
    if result[0]["start"]!=start or result[-1]["end"]!=end:raise DomainError("RANGE","总表区间须恰好覆盖拆分日")
    for left,right in zip(result,result[1:]):
        if left["end"]<right["start"]:raise DomainError("GAP","总表区间存在缺口")
        if left["end"]>right["start"]:raise DomainError("OVERLAP","总表区间重叠")
    return result
def pennies(raws,keys):
    target=sum(raws,D(0)).quantize(D(".01"),rounding=ROUND_HALF_UP)
    amounts=[r.quantize(D(".01"),rounding=ROUND_FLOOR) for r in raws]
    left=int((target-sum(amounts,D(0)))/D(".01"));order=sorted(range(len(raws)),key=lambda i:(-(raws[i]-amounts[i]),keys[i]))
    for i in order[:left]:amounts[i]+=D(".01")
    return amounts
def inherit(records,spec,loss_rate):
    start,end=day_bounds(spec["day"]);station=spec["station"]
    meters={};orders=[];others=0
    for row in records:
        if row["station"]!=station or row["end"]<=start or row["start"]>=end:others+=1;continue
        if row["kind"]=="station":meters[row["id"]]=row
        else:
            if row["start"]<start or row["end"]>end:raise DomainError("RANGE","订单超出拆分日，请先切成计量段")
            orders.append(row)
    extra=sorted(m for m in meters if m not in {z["meter"] for z in spec["zones"]})
    if extra:raise DomainError("CONFLICT","总表"+",".join(extra)+"未指定承接运营区")
    segs=segments(spec,meters)
    for row in orders:
        total=D(str((row["end"]-row["start"]).total_seconds()));parts=[]
        for seg in segs:
            a,b=max(row["start"],seg["start"]),min(row["end"],seg["end"])
            if a<b:parts.append([seg,row["energy"]*D(str((b-a).total_seconds()))/total])
        if not parts:raise DomainError("INCOMPLETE","订单未落入任何承接段")
        parts[-1][1]+=row["energy"]-sum((kwh for _,kwh in parts),D(0))
        for seg,kwh in parts:seg["orders"].append({"id":row["id"],"order":row["order"],"kwh":kwh})
    for seg in segs:
        seg["order_kwh"]=sum((p["kwh"] for p in seg["orders"]),D(0));seg["loss_kwh"]=seg["meter_kwh"]-seg["order_kwh"]
        if seg["loss_kwh"]<0:seg["loss_state"]="订单电量超过总表"
        elif not seg["orders"] and seg["loss_kwh"]>0:seg["loss_state"]="无订单承接损耗"
        else:seg["loss_state"]="通过"
    meter_total=sum((s["meter_kwh"] for s in segs),D(0));order_total=sum((r["energy"] for r in orders),D(0));loss_total=meter_total-order_total
    if sum((s["order_kwh"] for s in segs),D(0))!=order_total:raise DomainError("INCOMPLETE","分段订单电量不守恒")
    if sum((s["loss_kwh"] for s in segs),D(0))!=loss_total:raise DomainError("INCOMPLETE","分段损耗不守恒")
    raws=[s["loss_kwh"]*loss_rate for s in segs]
    amounts=pennies(raws,[s["zone"] for s in segs]) if all(s["loss_kwh"]>=0 for s in segs) else [r.quantize(D(".01"),rounding=ROUND_HALF_UP) for r in raws]
    zones=[{"zone":s["zone"],"meter":s["meter"],"start":s["start"],"end":s["end"],"meter_kwh":s["meter_kwh"],"order_kwh":s["order_kwh"],
            "loss_kwh":s["loss_kwh"],"loss_amount":amounts[i],"loss_state":s["loss_state"],"orders":s["orders"]} for i,s in enumerate(segs)]
    conservation={"meter_kwh":meter_total,"order_kwh":order_total,"loss_kwh":loss_total,"amount":sum(amounts,D(0)),"orders":len(orders),"zones":len(segs)}
    return zones,conservation
