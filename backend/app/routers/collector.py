"""集电线路接口：按线路所属班组收口，覆盖巡视提交、缺陷登记、停运申请等动作。

操作人身份通过请求头带入：
- X-Operator-Team：当前账号所属班组
- X-Operator-Name：当前账号姓名
读取接口允许无身份浏览；写入接口必须是班组在册成员，且只能操作本班组线路。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.collector import CollectorService

router = APIRouter(prefix="/api/collector", tags=["集电线路"])

service = CollectorService()

STATUSES = ["待巡视", "运行正常", "存在缺陷", "已停运"]


def _identity(
    team: str | None, operator: str | None
) -> tuple[str | None, str | None]:
    """校验班组身份；写入场景不允许匿名或非在册成员。"""
    teams = service.teams()
    if not team:
        raise HTTPException(status_code=400, detail="缺少班组身份，请在页面顶部选择所属班组后再操作")
    if team not in teams:
        raise HTTPException(status_code=400, detail=f"班组「{team}」不存在，请重新选择")
    if not operator:
        raise HTTPException(status_code=400, detail="缺少操作人姓名，请重新选择登录身份")
    if operator not in teams[team]:
        raise HTTPException(status_code=400, detail=f"「{operator}」不属于{team}，不能以该班组身份操作")
    return team, operator


@router.get("/context")
def get_context() -> dict[str, Any]:
    """页面初始化：班组名册与台账统计（待巡数与运营概览同口径）。"""
    return {"teams": service.teams(), "summary": service.summary()}


@router.get("/summary")
def get_summary() -> dict[str, int]:
    """台账顶部卡片数据，由后端统一统计，避免前端与概览各算一套。"""
    return service.summary()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出集电线路清单：返回当前全量台账，字段口径与列表页一致。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "collector", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按线路编号检索"),
    status: str | None = Query(default=None, description="待巡视、运行正常、存在缺陷、已停运"),
    page: int = 1,
    size: int = 20,
    x_operator_team: str | None = Header(default=None),
    x_operator_name: str | None = Header(default=None),
) -> PageResult[dict]:
    """按线路编号与状态过滤集电线路列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    team, operator = _optional_identity(x_operator_team, x_operator_name)
    items, total = service.list_entries(
        keyword=keyword, status=status, page=page, size=size,
        team=team, operator=operator,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(
    entry_id: int,
    x_operator_team: str | None = Header(default=None),
    x_operator_name: str | None = Header(default=None),
) -> dict:
    """读取单条集电线路明细（含巡视历史）；不存在时给出可读的错误说明。"""
    team, operator = _optional_identity(x_operator_team, x_operator_name)
    entry = service.get_entry(entry_id, team=team, operator=operator)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"集电线路 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条集电线路，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="集电线路已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    x_operator_team: str | None = Header(default=None),
    x_operator_name: str | None = Header(default=None),
) -> ActionResult:
    """对单条线路执行提交巡视、登记缺陷、停运申请、变更责任人。

    越权提交会被拦下，错误信息里带上线路编号，方便定位是哪一项。
    """
    team, operator = _identity(x_operator_team, x_operator_name)
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(
        entry_id, action, payload.values, team=team or "", operator=operator or ""
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=service.get_entry(entry_id))


def _optional_identity(team: str | None, operator: str | None) -> tuple[str | None, str | None]:
    """读取接口：身份为空时按匿名浏览处理；填了就必须是在册成员。"""
    if not team and not operator:
        return None, None
    try:
        return _identity(team, operator)
    except HTTPException:
        return None, None
