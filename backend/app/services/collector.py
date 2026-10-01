"""集电线路业务规则：按线路所属班组收口，状态口径、字段口径都收在这里。

权限原则：
- 本班组只能提交本班组线路的巡视结果与缺陷登记，别的班组只能查看；
- 停运申请必须由线路责任人本人提交并写明停运原因；
- 已停运线路对任何非归属班组只读，归属班组也只能登记/消除缺陷；
- 责任人变更只影响后续操作，历史巡视记录快照里仍是原班组、原巡视人。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store
from app.teams import ADMIN_NAME, TEAMS, is_member

MODULE = "collector"
PATROL_MODULE = "collector_patrol"
DEFECT_MODULE = "collector_defect"

REQUIRED_FIELDS = ["线路编号", "电压等级", "起止杆塔", "线路长度_km", "所属场站", "所属班组", "责任人"]
STATUS_ORDER = ["待巡视", "运行正常", "存在缺陷", "已停运"]
STOPPED = "已停运"
PENDING_PATROL = "待巡视"
DEFECTIVE = "存在缺陷"
HEALTHY = "运行正常"
DEFECT_LEVELS = ["一般", "严重", "紧急"]
PATROL_CONCLUSIONS = [HEALTHY, DEFECTIVE]


class ServiceError(Exception):
    """业务规则被违反；router 转成 {ok: false, message} 返回前端。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _clean(values: dict[str, Any], key: str) -> str:
    return str(values.get(key) or "").strip()


def format_length(value: Any) -> str:
    """线路长度统一口径：数值（km，保留两位小数）+ 单位。"""
    try:
        return f"{float(value):.2f} km"
    except (TypeError, ValueError):
        return "—"


def _open_defects(line_id: int) -> list[dict[str, Any]]:
    return [
        row for row in store.rows(DEFECT_MODULE)
        if int(row.get("线路id", 0)) == line_id and row.get("open")
    ]


def _last_patrol(line_id: int) -> dict[str, Any] | None:
    records = [
        row for row in store.rows(PATROL_MODULE) if int(row.get("线路id", 0)) == line_id
    ]
    return max(records, key=lambda row: str(row.get("巡视日期", "")), default=None)


def _recompute_status(line: dict[str, Any]) -> None:
    """让线路状态与缺陷台账、停运状态始终对得上。"""
    if line.get("status") == STOPPED:
        line["abnormal"] = True
        line["pending"] = False
        return
    line["status"] = DEFECTIVE if _open_defects(int(line["id"])) else HEALTHY
    line["abnormal"] = line["status"] == DEFECTIVE
    line["pending"] = False


def serialize(line: dict[str, Any]) -> dict[str, Any]:
    """台账对外字段：缺陷数量来自缺陷登记，线路状态与内部 status 同一来源。"""
    line_id = int(line["id"])
    last = _last_patrol(line_id)
    return {
        "id": line_id,
        "线路编号": line.get("线路编号"),
        "电压等级": line.get("电压等级"),
        "起止杆塔": line.get("起止杆塔"),
        "线路长度": format_length(line.get("线路长度_km")),
        "所属场站": line.get("所属场站"),
        "所属班组": line.get("所属班组"),
        "责任人": line.get("责任人"),
        "上次巡视日": (last or {}).get("巡视日期", "") or "—",
        "缺陷数量": len(_open_defects(line_id)),
        "线路状态": line.get("status"),
        "停运原因": line.get("停运原因", "") or "",
        "最新巡视": {
            "巡视单号": last.get("巡视单号"),
            "巡视日期": last.get("巡视日期"),
            "巡视结论": last.get("巡视结论"),
            "巡视人": last.get("巡视人"),
            "巡视班组": last.get("巡视班组"),
            "问题描述": last.get("问题描述", ""),
        } if last else None,
    }


def stats() -> dict[str, int]:
    """台账统计；待巡视口径与运营概览的 pending 完全一致。"""
    rows = store.rows(MODULE)
    return {
        "在运线路": sum(1 for row in rows if row.get("status") != STOPPED),
        "存在缺陷线路": sum(1 for row in rows if row.get("status") == DEFECTIVE),
        "待巡视线段": sum(1 for row in rows if row.get("status") == PENDING_PATROL),
        "已停运线路": sum(1 for row in rows if row.get("status") == STOPPED),
    }


def _next_id(module: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1


def _next_code(prefix: str, module: str, field: str) -> str:
    used = {str(row.get(field, "")) for row in store.rows(module)}
    seq = _next_id(module)
    while True:
        code = f"{prefix}-{seq:04d}"
        if code not in used:
            return code
        seq += 1


class CollectorService:
    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        team: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("线路编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if team:
            rows = [row for row in rows if row.get("所属班组") == team]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [serialize(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        line = store.find(MODULE, entry_id)
        return serialize(line) if line else None

    def get_detail(self, entry_id: int) -> dict[str, Any]:
        line = store.find(MODULE, entry_id)
        if line is None:
            raise ServiceError(f"集电线路 {entry_id} 不存在或已归档")
        patrols = sorted(
            (row for row in store.rows(PATROL_MODULE) if int(row.get("线路id", 0)) == entry_id),
            key=lambda row: str(row.get("巡视日期", "")),
            reverse=True,
        )
        defects = sorted(
            (row for row in store.rows(DEFECT_MODULE) if int(row.get("线路id", 0)) == entry_id),
            key=lambda row: (bool(row.get("open")), str(row.get("登记日期", ""))),
            reverse=True,
        )
        return {
            "line": serialize(line),
            "patrols": [dict(row) for row in patrols],
            "defects": [dict(row) for row in defects],
        }

    # ---------- 权限 ----------
    @staticmethod
    def _line_or_raise(entry_id: int) -> dict[str, Any]:
        line = store.find(MODULE, entry_id)
        if line is None:
            raise ServiceError(f"线路 #{entry_id} 不存在或已归档")
        return line

    @staticmethod
    def _require_team(line: dict[str, Any], operator: str) -> None:
        team = str(line.get("所属班组") or "")
        label = f"线路 {line.get('线路编号')}（{line.get('起止杆塔')}）"
        if operator == ADMIN_NAME:
            raise ServiceError(
                f"{label} 归属{team}：值班管理员只能查看或变更责任人，不能代班组提交巡视与缺陷"
            )
        if not is_member(team, operator):
            raise ServiceError(
                f"越权操作被拦截：{label} 归属{team}，"
                f"当前操作人「{operator}」不属于该班组，只能查看，不能提交"
            )

    # ---------- 动作：提交巡视结果 ----------
    def submit_patrol(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        line = self._line_or_raise(entry_id)
        operator = _clean(values, "operator")
        self._require_team(line, operator)

        label = f"线路 {line.get('线路编号')}（{line.get('起止杆塔')}）"
        if line.get("status") == STOPPED:
            raise ServiceError(f"{label} 已停运（{line.get('停运原因') or '—'}），停运期间不能提交巡视结果")

        conclusion = _clean(values, "巡视结论")
        if conclusion not in PATROL_CONCLUSIONS:
            raise ServiceError(f"{label} 的巡视结论必须是「{HEALTHY}」或「{DEFECTIVE}」")
        patrol_date = _clean(values, "巡视日期") or date.today().isoformat()
        description = _clean(values, "问题描述")
        open_count = len(_open_defects(entry_id))

        if conclusion == HEALTHY and (description or open_count):
            extra = "该线路仍有未消除缺陷" if open_count else "本次巡视已填写问题描述"
            raise ServiceError(
                f"{label} 巡视结论与内容对不上：结论选了「{HEALTHY}」，但{extra}，"
                "请登记缺陷后改选「存在缺陷」，或先消除既有缺陷"
            )
        if conclusion == DEFECTIVE and not description:
            raise ServiceError(f"{label} 巡视结论为「{DEFECTIVE}」时必须填写问题/缺陷描述")

        record = {
            "id": _next_id(PATROL_MODULE),
            "status": "已提交",
            "pending": False,
            "abnormal": conclusion == DEFECTIVE,
            "巡视单号": _next_code("CPATR", PATROL_MODULE, "巡视单号"),
            "线路编号": line.get("线路编号"),
            "线路id": entry_id,
            "巡视日期": patrol_date,
            "巡视结论": conclusion,
            "巡视人": operator,
            # 归属快照：责任人以后变更，历史记录仍归原班组
            "巡视班组": line.get("所属班组"),
            "问题描述": description,
        }

        if conclusion == DEFECTIVE:
            defect = {
                "id": _next_id(DEFECT_MODULE),
                "status": "未消除",
                "pending": True,
                "abnormal": True,
                "缺陷编号": _next_code("CDEFE", DEFECT_MODULE, "缺陷编号"),
                "线路编号": line.get("线路编号"),
                "线路id": entry_id,
                "缺陷内容": description,
                "缺陷等级": _clean(values, "缺陷等级") or "一般",
                "登记日期": patrol_date,
                "登记人": operator,
                "登记班组": line.get("所属班组"),
                "来源巡视单": record["巡视单号"],
                "open": True,
            }
            if defect["缺陷等级"] not in DEFECT_LEVELS:
                raise ServiceError("缺陷等级必须是：一般、严重、紧急")
            store.rows(DEFECT_MODULE).append(defect)
            record["缺陷数量"] = open_count + 1
        else:
            record["缺陷数量"] = 0

        store.rows(PATROL_MODULE).append(record)
        _recompute_status(line)
        line["上次巡视日"] = patrol_date
        return serialize(line), f"{line.get('线路编号')} 巡视结果已提交（{record['巡视单号']}，结论：{conclusion}）"

    # ---------- 动作：登记缺陷 ----------
    def register_defect(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        line = self._line_or_raise(entry_id)
        operator = _clean(values, "operator")
        self._require_team(line, operator)

        label = f"线路 {line.get('线路编号')}（{line.get('起止杆塔')}）"
        content = _clean(values, "缺陷内容")
        if not content:
            raise ServiceError(f"{label} 登记缺陷时必须填写缺陷内容")
        level = _clean(values, "缺陷等级") or "一般"
        if level not in DEFECT_LEVELS:
            raise ServiceError("缺陷等级必须是：一般、严重、紧急")

        record_date = _clean(values, "登记日期") or date.today().isoformat()
        defect = {
            "id": _next_id(DEFECT_MODULE),
            "status": "未消除",
            "pending": True,
            "abnormal": True,
            "缺陷编号": _next_code("CDEFE", DEFECT_MODULE, "缺陷编号"),
            "线路编号": line.get("线路编号"),
            "线路id": entry_id,
            "缺陷内容": content,
            "缺陷等级": level,
            "登记日期": record_date,
            "登记人": operator,
            "登记班组": line.get("所属班组"),
            "来源巡视单": "",
            "open": True,
        }
        store.rows(DEFECT_MODULE).append(defect)
        _recompute_status(line)
        return serialize(line), f"{line.get('线路编号')} 缺陷已登记（{defect['缺陷编号']}，等级：{level}）"

    # ---------- 动作：缺陷消除（已停运线路仍可由归属班组消缺） ----------
    def resolve_defect(self, defect_id: int, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        defect = store.find(DEFECT_MODULE, defect_id)
        if defect is None:
            raise ServiceError(f"缺陷 #{defect_id} 不存在或已归档")
        operator = _clean(values, "operator")
        line = self._line_or_raise(int(defect["线路id"]))
        self._require_team(line, operator)

        if not defect.get("open"):
            raise ServiceError(f"缺陷 {defect.get('缺陷编号')} 已消除，不能重复消除")
        defect["open"] = False
        defect["status"] = "已消除"
        defect["pending"] = False
        defect["abnormal"] = False
        defect["消除日期"] = _clean(values, "消除日期") or date.today().isoformat()
        defect["消除人"] = operator
        _recompute_status(line)
        return serialize(line), f"{defect.get('缺陷编号')} 已消除，{line.get('线路编号')} 状态已重新核算"

    # ---------- 动作：申请停运（责任人本人 + 必填停运原因） ----------
    def stop_line(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        line = self._line_or_raise(entry_id)
        operator = _clean(values, "operator")
        self._require_team(line, operator)

        label = f"线路 {line.get('线路编号')}（{line.get('起止杆塔')}）"
        if operator != str(line.get("责任人") or ""):
            raise ServiceError(
                f"{label} 停运申请必须由线路责任人「{line.get('责任人')}」提交，"
                f"「{operator}」无权申请停运"
            )
        reason = _clean(values, "停运原因")
        if not reason:
            raise ServiceError(f"{label} 申请停运必须写明停运原因")
        if line.get("status") == STOPPED:
            raise ServiceError(f"{label} 已是停运状态，请勿重复申请")

        line["status"] = STOPPED
        line["停运原因"] = reason
        line["pending"] = False
        line["abnormal"] = True
        return serialize(line), f"{line.get('线路编号')} 停运申请已提交（责任人：{operator}，原因：{reason}）"

    # ---------- 动作：变更责任人（仅管理员；历史记录不动） ----------
    def change_owner(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        line = self._line_or_raise(entry_id)
        operator = _clean(values, "operator")
        if operator != ADMIN_NAME:
            raise ServiceError("只有值班管理员可以变更线路责任人")

        label = f"线路 {line.get('线路编号')}（{line.get('起止杆塔')}）"
        new_owner = _clean(values, "责任人")
        new_team = _clean(values, "所属班组") or str(line.get("所属班组") or "")
        if new_team not in TEAMS:
            raise ServiceError(f"目标班组「{new_team}」不存在")
        if not new_owner or not is_member(new_team, new_owner):
            members = "、".join(TEAMS[new_team]["members"])
            raise ServiceError(f"责任人「{new_owner}」不在{new_team}成员名单内（可选：{members}）")

        old_team, old_owner = line.get("所属班组"), line.get("责任人")
        line["所属班组"] = new_team
        line["责任人"] = new_owner
        return serialize(line), (
            f"{label} 责任人已变更：{old_team}/{old_owner} → {new_team}/{new_owner}；"
            "历史巡视记录仍归原班组"
        )

    # ---------- 登记（沿用台账字段口径） ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not _clean(values, field)]
        if missing:
            return None, missing
        team = _clean(values, "所属班组")
        owner = _clean(values, "责任人")
        if team not in TEAMS:
            missing.append("所属班组")
            return None, missing
        if not is_member(team, owner):
            missing.append("责任人(须为该班组成员)")
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = _clean(values, field)
        try:
            entry["线路长度_km"] = float(entry["线路长度_km"])
        except ValueError:
            return None, ["线路长度_km(须为数字)"]
        entry["status"] = PENDING_PATROL
        entry["pending"] = True
        entry["abnormal"] = False
        entry["停运原因"] = ""
        entry["上次巡视日"] = ""
        rows.append(entry)
        return serialize(entry), []
