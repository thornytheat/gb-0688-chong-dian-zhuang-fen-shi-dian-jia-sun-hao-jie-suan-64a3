import pytest
from decimal import Decimal as D
from app.config import SAMPLES
from app.modules.m8_splits import service
@pytest.fixture
def split_text(): return (SAMPLES/"split.csv").read_text(encoding="utf-8")
@pytest.fixture
def spec():
    return {"split":{"station":"站甲","day":"2026-11-17","zones":[{"name":"站甲·东","meter":"M0A"},{"name":"站甲·西","meter":"M0B"}]}}
def execute(client,text,params): return client.post("/api/m8",json={"text":text,"params":params})
def test_segments_assigned_to_zones(client,split_text,spec):
    reply=execute(client,split_text,spec);assert reply.status_code==200
    result=reply.json
    assert result["station"]=="站甲" and result["day"]=="2026-11-17" and result["state"]=="生效" and result["settleable"]
    east,west=result["zones"]
    assert (east["zone"],east["meter"],east["loss_state"])==("站甲·东","M0A","通过")
    assert (west["zone"],west["meter"],west["loss_state"])==("站甲·西","M0B","通过")
    assert D(east["meter_kwh"])==33 and D(east["order_kwh"])==25 and D(east["loss_kwh"])==8
    assert D(west["meter_kwh"])==47 and D(west["order_kwh"])==43 and D(west["loss_kwh"])==4
    assert D(east["loss_amount"])==D("5.20") and D(west["loss_amount"])==D("2.60")
def test_straddling_order_splits_by_time(client,split_text,spec):
    result=execute(client,split_text,spec).json
    east,west=result["zones"]
    o103_east=next(o for o in east["orders"] if o["order"]=="O103")
    o103_west=next(o for o in west["orders"] if o["order"]=="O103")
    assert D(o103_east["kwh"])==4 and D(o103_west["kwh"])==4
def test_conservation_exact(client,split_text,spec):
    result=execute(client,split_text,spec).json
    total=result["conservation"]
    assert D(total["meter_kwh"])==80 and D(total["order_kwh"])==68 and D(total["loss_kwh"])==12
    assert sum(D(z["order_kwh"]) for z in result["zones"])==D(total["order_kwh"])
    assert sum(D(z["loss_kwh"]) for z in result["zones"])==D(total["loss_kwh"])
    assert sum(D(z["loss_amount"]) for z in result["zones"])==D(total["amount"])==D("7.80")
    assert result["input_count"]==result["retained"]+result["isolated"]
def test_reexecute_is_idempotent(client,split_text,spec):
    first=execute(client,split_text,spec).json
    second=execute(client,split_text,spec).json
    assert first["split_id"]==second["split_id"] and first["created"]==second["created"]
    assert len(client.get("/api/m8").json["splits"])==1
def test_same_day_unique_active(client,split_text,spec):
    assert execute(client,split_text,spec).status_code==200
    other={"split":{"station":"站甲","day":"2026-11-17","zones":[{"name":"东区","meter":"M0A"},{"name":"西区","meter":"M0B"}]}}
    reply=execute(client,split_text,other)
    assert reply.status_code==409 and reply.json["code"]=="CONFLICT"
    assert len(client.get("/api/m8").json["splits"])==1
def test_rollback_restores_and_keeps_record(client,split_text,spec):
    result=execute(client,split_text,spec).json;split_id=result["split_id"]
    stale=client.post(f"/api/m8/{split_id}/rollback",json={"version":9})
    assert stale.status_code==409
    reply=client.post(f"/api/m8/{split_id}/rollback",json={"version":result["version"]})
    assert reply.status_code==200
    rolled=reply.json
    assert rolled["state"]=="已回滚" and rolled["version"]==result["version"]+1
    assert client.get(f"/api/m8/{split_id}").status_code==200
    assert len(client.get("/api/m8").json["splits"])==1
    again=client.post(f"/api/m8/{split_id}/rollback",json={"version":result["version"]})
    assert again.status_code==409
def test_day_freed_after_rollback(client,split_text,spec):
    result=execute(client,split_text,spec).json
    client.post(f"/api/m8/{result['split_id']}/rollback",json={"version":result["version"]})
    same=execute(client,split_text,spec).json
    assert same["split_id"]==result["split_id"] and same["state"]=="已回滚"
    assert len(client.get("/api/m8").json["splits"])==1
    fixed={"split":{"station":"站甲","day":"2026-11-17","zones":[{"name":"东区","meter":"M0A"},{"name":"西区","meter":"M0B"}]}}
    reply=execute(client,split_text,fixed)
    assert reply.status_code==200 and reply.json["split_id"]!=result["split_id"] and reply.json["state"]=="生效"
    assert len(client.get("/api/m8").json["splits"])==2
def test_failed_split_leaves_nothing(client,split_text,spec):
    gapped=split_text.replace("2026-11-17T12:00:00+08:00,2026-11-18T00:00:00+08:00,47","2026-11-17T13:00:00+08:00,2026-11-18T00:00:00+08:00,47")
    reply=execute(client,gapped,spec);assert reply.status_code==422 and reply.json["code"]=="GAP"
    overlapped=split_text.replace("2026-11-17T12:00:00+08:00,2026-11-18T00:00:00+08:00,47","2026-11-17T11:00:00+08:00,2026-11-18T00:00:00+08:00,47")
    assert execute(client,overlapped,spec).json["code"]=="OVERLAP"
    one_meter=split_text.replace("M0B,站甲,,2026-11-17T12:00:00+08:00,2026-11-18T00:00:00+08:00,47,kWh,0,1,station\n","")
    missing={"split":{"station":"站甲","day":"2026-11-17","zones":[{"name":"站甲·东","meter":"M0A"},{"name":"站甲·西","meter":"M9X"}]}}
    assert execute(client,one_meter,missing).json["code"]=="ORPHAN"
    strayed=split_text+"00107,站甲,O107,2026-11-17T23:00:00+08:00,2026-11-18T01:00:00+08:00,5,kWh,4.0,1,order\n"
    assert execute(client,strayed,spec).json["code"]=="RANGE"
    assert client.get("/api/m8").json["splits"]==[]
def test_unmapped_meter_rejected(client,split_text,spec):
    extra=split_text+"M0C,站甲,,2026-11-17T08:00:00+08:00,2026-11-17T09:00:00+08:00,1,kWh,0,1,station\n"
    reply=execute(client,extra,spec)
    assert reply.status_code==422 and reply.json["code"]=="CONFLICT"
    assert client.get("/api/m8").json["splits"]==[]
def test_bad_specs_rejected(client,split_text):
    one={"split":{"station":"站甲","day":"2026-11-17","zones":[{"name":"站甲·东","meter":"M0A"}]}}
    assert execute(client,split_text,one).json["code"]=="LIMIT"
    reused={"split":{"station":"站甲","day":"2026-11-17","zones":[{"name":"站甲","meter":"M0A"},{"name":"站甲·西","meter":"M0B"}]}}
    assert execute(client,split_text,reused).json["code"]=="CONFLICT"
    bad_day={"split":{"station":"站甲","day":"11-17","zones":[{"name":"站甲·东","meter":"M0A"},{"name":"站甲·西","meter":"M0B"}]}}
    assert execute(client,split_text,bad_day).json["code"]=="TIME"
    assert execute(client,split_text,{}).json["code"]=="PARAMS"
    assert client.get("/api/m8").json["splits"]==[]
def test_reviewed_runs_untouched(client,split_text,spec):
    run=client.post("/api/runs",json={}).json
    run_id=run["manifest"]["run_id"]
    assert client.post("/api/review/"+run_id,json={"version":run["version"],"decision":"通过"}).status_code==200
    before=client.get("/api/runs/"+run_id).json
    assert execute(client,split_text,spec).status_code==200
    after=client.get("/api/runs/"+run_id).json
    assert before==after and after["review"]=="通过"
    assert client.get(f"/m/7?run={run_id}").status_code==200
def test_run_source_and_cross_channel_idempotent(client,split_text,spec):
    run=client.post("/api/runs",json={"text":split_text}).json
    run_id=run["manifest"]["run_id"]
    by_run=client.post("/api/m8",json={"run_id":run_id,"params":spec})
    assert by_run.status_code==200 and by_run.json["basis"]["source"]=="run" and by_run.json["basis"]["run_id"]==run_id
    assert D(by_run.json["conservation"]["loss_kwh"])==12
    by_text=execute(client,split_text,spec)
    assert by_text.status_code==200 and by_text.json["split_id"]==by_run.json["split_id"]
    assert len(client.get("/api/m8").json["splits"])==1
def test_basis_run_must_exist(client,split_text):
    spec={"split":{"station":"站甲","day":"2026-11-17","basis_run":"missing","zones":[{"name":"站甲·东","meter":"M0A"},{"name":"站甲·西","meter":"M0B"}]}}
    assert execute(client,split_text,spec).status_code==404
def test_penny_distribution(client):
    text=("id,station,order,start,end,energy,unit,bill,version,kind\n"
          "P1,站甲,PA,2026-11-17T00:00:00+08:00,2026-11-17T12:00:00+08:00,10,kWh,0,1,order\n"
          "P2,站甲,PB,2026-11-17T12:00:00+08:00,2026-11-18T00:00:00+08:00,20,kWh,0,1,order\n"
          "MA,站甲,,2026-11-17T00:00:00+08:00,2026-11-17T12:00:00+08:00,10.335,kWh,0,1,station\n"
          "MB,站甲,,2026-11-17T12:00:00+08:00,2026-11-18T00:00:00+08:00,20.665,kWh,0,1,station\n")
    spec={"split":{"station":"站甲","day":"2026-11-17","zones":[{"name":"东","meter":"MA"},{"name":"西","meter":"MB"}]}}
    result=execute(client,text,spec).json
    east,west=result["zones"]
    assert D(east["loss_amount"])==D("0.22") and D(west["loss_amount"])==D("0.43")
    assert D(result["conservation"]["amount"])==D("0.65")
def test_negative_loss_flagged(client):
    text=("id,station,order,start,end,energy,unit,bill,version,kind\n"
          "P1,站甲,PA,2026-11-17T00:00:00+08:00,2026-11-17T12:00:00+08:00,30,kWh,0,1,order\n"
          "MA,站甲,,2026-11-17T00:00:00+08:00,2026-11-17T12:00:00+08:00,20,kWh,0,1,station\n"
          "MB,站甲,,2026-11-17T12:00:00+08:00,2026-11-18T00:00:00+08:00,10,kWh,0,1,station\n")
    spec={"split":{"station":"站甲","day":"2026-11-17","zones":[{"name":"东","meter":"MA"},{"name":"西","meter":"MB"}]}}
    result=execute(client,text,spec).json
    assert result["zones"][0]["loss_state"]=="订单电量超过总表" and not result["settleable"]
def test_pages(client,split_text,spec):
    assert client.get("/m/8").status_code==200
    assert "拆分承接" in client.get("/m/8").get_data(as_text=True)
    result=execute(client,split_text,spec).json
    page=client.get(f"/m/8?split={result['split_id']}")
    assert page.status_code==200
    body=page.get_data(as_text=True)
    assert "站甲·东" in body and "M0A" in body and "8.000" in body and "承接依据" in body
    assert "/m/8" in client.get("/m/1").get_data(as_text=True)
def test_api_detail_and_missing(client,split_text,spec):
    result=execute(client,split_text,spec).json
    assert client.get(f"/api/m8/{result['split_id']}").json["split_id"]==result["split_id"]
    assert client.get("/api/m8/none").status_code==404
    listing=client.get("/api/m8").json["splits"][0]
    assert listing["station"]=="站甲" and listing["day"]=="2026-11-17" and listing["state"]=="生效"
    assert D(listing["loss_kwh"])==12 and D(listing["loss_amount"])==D("7.80")
def test_rollback_missing_record(client):
    assert client.post("/api/m8/none/rollback",json={"version":1}).status_code==404
def test_other_stations_ignored(client,split_text,spec):
    extra=split_text+"00201,站乙,O201,2026-11-17T10:00:00+08:00,2026-11-17T11:00:00+08:00,9,kWh,7.2,1,order\n"
    result=execute(client,extra,spec).json
    assert D(result["conservation"]["order_kwh"])==68 and D(result["conservation"]["loss_kwh"])==12
