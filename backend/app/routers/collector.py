"""集电线路接口：按所属班组收口的巡视、缺陷登记、停运申请与责任人变更。

所有动作接口统一返回 {ok, message, entry?}：业务/权限不满足时 ok=false 并说明
具体是哪一条线路、哪一项被拦，由前端在对应行给出提示。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.collector import (
    DEFECTIVE,
    PENDING_PATROL,
    STOPPED,
    CollectorService,
    ServiceError,
    stats,
)
from app.teams import teams_payload

router = APIRouter(prefix="/api/collector", tags=["集电线路"])

service = CollectorService()

STATUSES = [PENDING_PATROL, "运行正常", DEFECTIVE, STOPPED]


def _fail(exc: ServiceError) -> ActionResult:
    return ActionResult(ok=False, message=exc.message)


@router.get("/teams")
def list_teams() -> dict[str, Any]:
    """班组与成员名单：前端权限渲染、人员下拉都以这里为准。"""
    return teams_payload()


@router.get("/stats")
def get_stats() -> dict[str, int]:
    """台账统计；待巡视线段口径与 /api/overview 的 pending 一致。"""
    return stats()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按线路编号检索"),
    status: str | None = Query(default=None, description="待巡视、运行正常、存在缺陷、已停运"),
    team: str | None = Query(default=None, description="按所属班组过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按线路编号、状态与所属班组过滤集电线路列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, team=team, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出集电线路清单：与列表同一套字段口径。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "collector", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条集电线路明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"集电线路 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/detail")
def get_detail(entry_id: int) -> dict[str, Any]:
    """线路台账 + 历史巡视记录 + 缺陷登记，供详情抽屉核对责任归属与巡视结论。"""
    try:
        return service.get_detail(entry_id)
    except ServiceError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条集电线路，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段或取值不合法：{'、'.join(missing)}")
    return ActionResult(ok=True, message="集电线路已登记", entry=entry)


@router.post("/{entry_id}/patrol", response_model=ActionResult)
def submit_patrol(entry_id: int, payload: EntryPayload) -> ActionResult:
    """提交巡视结果：仅本班组可提交；结论必须与问题描述、缺陷台账对得上。"""
    try:
        entry, message = service.submit_patrol(entry_id, payload.values)
    except ServiceError as exc:
        return _fail(exc)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/defects", response_model=ActionResult)
def register_defect(entry_id: int, payload: EntryPayload) -> ActionResult:
    """登记缺陷：仅本班组可提交；提交后线路状态自动核为存在缺陷。"""
    try:
        entry, message = service.register_defect(entry_id, payload.values)
    except ServiceError as exc:
        return _fail(exc)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/stop", response_model=ActionResult)
def stop_line(entry_id: int, payload: EntryPayload) -> ActionResult:
    """申请停运：仅线路责任人本人可提交，必须写明停运原因。"""
    try:
        entry, message = service.stop_line(entry_id, payload.values)
    except ServiceError as exc:
        return _fail(exc)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/owner", response_model=ActionResult)
def change_owner(entry_id: int, payload: EntryPayload) -> ActionResult:
    """变更责任人：仅值班管理员；历史巡视记录保留原班组快照。"""
    try:
        entry, message = service.change_owner(entry_id, payload.values)
    except ServiceError as exc:
        return _fail(exc)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/defects/{defect_id}/resolve", response_model=ActionResult)
def resolve_defect(defect_id: int, payload: EntryPayload) -> ActionResult:
    """消除缺陷：仅本班组；消除后线路无其它未消缺陷时回到运行正常（停运线路除外）。"""
    try:
        entry, message = service.resolve_defect(defect_id, payload.values)
    except ServiceError as exc:
        return _fail(exc)
    return ActionResult(ok=True, message=message, entry=entry)
