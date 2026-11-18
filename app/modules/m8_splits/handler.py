from flask import Blueprint,request,jsonify
from app import store
from app.errors import DomainError
from . import service
bp=Blueprint("m8",__name__)
@bp.route("/api/m8",methods=["GET","POST"])
def endpoint():
    if request.method=="GET":return jsonify({"splits":store.splits_history()})
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):raise DomainError("BODY","请求必须是对象")
    return jsonify(service.execute(text=payload.get("text"),run_id=payload.get("run_id"),params=payload.get("params")))
@bp.get("/api/m8/<split_id>")
def detail(split_id):return jsonify(store.fetch_split(split_id))
@bp.post("/api/m8/<split_id>/rollback")
def rollback(split_id):
    data=request.get_json(silent=True)
    if not isinstance(data,dict):raise DomainError("BODY","请求必须是对象")
    return jsonify(store.rollback_split(split_id,data.get("version")))
