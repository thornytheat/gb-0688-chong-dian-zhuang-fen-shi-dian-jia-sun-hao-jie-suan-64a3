import os,sqlite3,json
from pathlib import Path
from app.errors import DomainError
def connection():
    path=Path(os.environ.get("DATA_DIR","data"));path.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path/"runs.sqlite",timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,review TEXT NOT NULL DEFAULT '待复核')")
    db.execute("CREATE TABLE IF NOT EXISTS splits (id TEXT PRIMARY KEY,station TEXT NOT NULL,day TEXT NOT NULL,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,state TEXT NOT NULL DEFAULT '生效')")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS splits_active_day ON splits(station,day) WHERE state='生效'")
    return db
def save(result):
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES(?,?)",(result["manifest"]["run_id"],json.dumps(result,ensure_ascii=False)))
    return fetch(result["manifest"]["run_id"])
def fetch(run_id):
    with connection() as db: row=db.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
    if row is None: raise DomainError("NOT_FOUND","批次不存在",404)
    result=json.loads(row["payload"]);result["version"]=row["version"];result["review"]=row["review"]
    return result
def history():
    with connection() as db: rows=db.execute("SELECT id,version,review FROM runs ORDER BY rowid DESC LIMIT 100").fetchall()
    return [dict(row) for row in rows]
def review(run_id,version,decision):
    if decision not in ("通过","退回"): raise DomainError("REVIEW","请选择通过或退回")
    if not isinstance(version,int): raise DomainError("STALE","版本必须为整数")
    with connection() as db:
        cur=db.execute("UPDATE runs SET review=?,version=version+1 WHERE id=? AND version=?",(decision,run_id,version))
        if cur.rowcount!=1: raise DomainError("STALE","复核版本已更新",409)
    return fetch(run_id)
def save_split(result):
    split_id=result["split_id"]
    with connection() as db:
        try:
            db.execute("INSERT INTO splits(id,station,day,payload) VALUES(?,?,?,?)",(split_id,result["station"],result["day"],json.dumps(result,ensure_ascii=False)))
        except sqlite3.IntegrityError:
            if db.execute("SELECT 1 FROM splits WHERE id=?",(split_id,)).fetchone() is None:
                raise DomainError("CONFLICT","当日已有生效的损耗承接结果，请先回滚再重新拆分",409)
    return fetch_split(split_id)
def fetch_split(split_id):
    with connection() as db: row=db.execute("SELECT * FROM splits WHERE id=?",(split_id,)).fetchone()
    if row is None: raise DomainError("NOT_FOUND","拆分记录不存在",404)
    result=json.loads(row["payload"]);result["version"]=row["version"];result["state"]=row["state"]
    return result
def splits_history():
    with connection() as db: rows=db.execute("SELECT id,station,day,state,version,payload FROM splits ORDER BY rowid DESC LIMIT 100").fetchall()
    result=[]
    for row in rows:
        payload=json.loads(row["payload"])
        result.append({"id":row["id"],"station":row["station"],"day":row["day"],"state":row["state"],"version":row["version"],
                       "zones":len(payload["zones"]),"loss_kwh":payload["conservation"]["loss_kwh"],"loss_amount":payload["conservation"]["amount"],"settleable":payload["settleable"]})
    return result
def rollback_split(split_id,version):
    if not isinstance(version,int): raise DomainError("STALE","版本必须为整数")
    with connection() as db:
        cur=db.execute("UPDATE splits SET state='已回滚',version=version+1 WHERE id=? AND version=? AND state='生效'",(split_id,version))
        if cur.rowcount!=1:
            if db.execute("SELECT 1 FROM splits WHERE id=?",(split_id,)).fetchone() is None: raise DomainError("NOT_FOUND","拆分记录不存在",404)
            raise DomainError("STALE","承接版本已更新或已回滚",409)
    return fetch_split(split_id)
