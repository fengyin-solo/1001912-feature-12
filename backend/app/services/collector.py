"""集电线路业务规则：按所属班组收口权限、巡视结论驱动状态、台账与概览同口径。

口径约定：
- 列表、明细、导出统一经 ``_present`` 输出，起止杆塔、线路长度只有一种展示格式；
- 非停运线路的状态以最近一次巡视/缺陷结论为准，责任归属与巡视结论始终对得上；
- 巡视历史在写入时冻结当时的班组与提交人，责任人变更不改写历史记录；
- 待巡视 = status 为「待巡视」，本台账统计与运营概览 overview 共用同一口径。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "collector"
REQUIRED_FIELDS = ["线路编号", "电压等级", "所属场站", "起始杆塔", "终止杆塔", "所属班组", "责任人"]
PENDING_STATUS = "待巡视"
STOPPED_STATUS = "已停运"
STATUS_ORDER = ["待巡视", "运行正常", "存在缺陷", "已停运"]
PATROL_RESULTS = ["运行正常", "存在缺陷"]
RECORD_TYPES = ["巡视", "缺陷登记", "停运", "责任人变更"]

# 班组与成员名单：同一账号只归属一个班组，跨班组只能查看。
TEAMS: dict[str, list[str]] = {
    "输电一班": ["张伟", "李娜", "周杰"],
    "输电二班": ["王强", "赵敏", "陈刚"],
}

LIST_COLUMNS = [
    "线路编号", "电压等级", "所属场站", "起止杆塔", "线路长度",
    "所属班组", "责任人", "上次巡视日", "缺陷数量", "线路状态",
]


def today_str() -> str:
    return date.today().isoformat()


class CollectorService:
    # ---- 读取 ----------------------------------------------------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        team: str | None = None,
        operator: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("线路编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        return [self._present(row, team=team, operator=operator) for row in page_rows], total

    def summary(self) -> dict[str, int]:
        """台账顶部统计：待巡数与 /api/overview 中集电线路的 pending 同口径。"""
        rows = store.rows(MODULE)
        return {
            "在运线路": sum(1 for row in rows if row.get("status") != STOPPED_STATUS),
            "存在缺陷线路": sum(1 for row in rows if row.get("status") == "存在缺陷"),
            "待巡视线段": sum(1 for row in rows if row.get("status") == PENDING_STATUS),
        }

    def get_entry(
        self,
        entry_id: int,
        *,
        team: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        view = self._present(entry, team=team, operator=operator)
        view["巡视历史"] = list(entry.get("巡视历史", []))
        return view

    def teams(self) -> dict[str, list[str]]:
        return dict(TEAMS)

    def reconcile_all(self) -> None:
        """按巡视结论对全部线路重新对账状态，供运营概览汇总前统一口径。"""
        for row in store.rows(MODULE):
            if row.get("status") != STOPPED_STATUS:
                self._sync_status(row)

    # ---- 写入 ----------------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        team_name = str(values["所属班组"]).strip()
        owner = str(values["责任人"]).strip()
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({
            "线路编号": str(values["线路编号"]).strip(),
            "电压等级": str(values["电压等级"]).strip(),
            "所属场站": str(values["所属场站"]).strip(),
            "起始杆塔": str(values["起始杆塔"]).strip(),
            "终止杆塔": str(values["终止杆塔"]).strip(),
            "线路长度km": self._parse_length(values.get("线路长度km", values.get("线路长度"))),
            "所属班组": team_name,
            "责任人": owner,
            "上次巡视日": None,
            "缺陷数量": 0,
            "停运原因": None,
            "巡视历史": [],
        })
        self._sync_status(entry)
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any],
        *,
        team: str,
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"集电线路 {entry_id} 不存在或已归档"

        allowed = ["提交巡视", "登记缺陷", "停运线路", "变更责任人"]
        if action not in allowed:
            return None, f"动作「{action}」不属于集电线路可执行范围"

        line_no = str(entry.get("线路编号") or entry_id)
        owner_team = str(entry.get("所属班组") or "")
        # 收口第一步：本班组只能提交本班组线路，别的班组只读。
        if team != owner_team:
            return None, (
                f"线路 {line_no} 归属{owner_team}，当前账号为{team}，"
                "跨班组只能查看，不能提交巡视或登记缺陷"
            )

        if action == "停运线路":
            return self._stop_line(entry, values, operator=operator)
        if action == "变更责任人":
            return self._change_owner(entry, values, team=team, operator=operator)

        # 停运线路在其它班组视图里只读；本班组同样冻结，需复役后再巡视。
        if entry.get("status") == STOPPED_STATUS:
            return None, f"线路 {line_no} 已停运，停运期间为只读状态，不能{action}"

        if action == "提交巡视":
            return self._submit_patrol(entry, values, team=team, operator=operator)
        return self._register_defect(entry, values, team=team, operator=operator)

    # ---- 各动作 --------------------------------------------------------
    def _submit_patrol(
        self, entry: dict[str, Any], values: dict[str, Any], *, team: str, operator: str
    ) -> tuple[dict[str, Any] | None, str]:
        result = str(values.get("巡视结论") or "").strip()
        if result not in PATROL_RESULTS:
            return None, "提交巡视需写明巡视结论：运行正常 或 存在缺陷"
        if not operator:
            return None, "提交人不能为空"
        record_day = str(values.get("巡视日期") or today_str()).strip()
        note = str(values.get("巡视说明") or "").strip()
        entry["巡视历史"].append({
            "日期": record_day,
            "类型": "巡视",
            "巡视结论": result,
            "说明": note,
            "班组": team,
            "提交人": operator,
        })
        entry["上次巡视日"] = record_day
        self._sync_status(entry)
        return entry, f"线路 {entry['线路编号']} 巡视结果已提交，结论：{result}"

    def _register_defect(
        self, entry: dict[str, Any], values: dict[str, Any], *, team: str, operator: str
    ) -> tuple[dict[str, Any] | None, str]:
        description = str(values.get("缺陷描述") or "").strip()
        if not description:
            return None, f"线路 {entry.get('线路编号')} 登记缺陷需填写缺陷描述"
        record_day = str(values.get("发现日期") or today_str()).strip()
        entry["巡视历史"].append({
            "日期": record_day,
            "类型": "缺陷登记",
            "巡视结论": "存在缺陷",
            "说明": description,
            "班组": team,
            "提交人": operator,
        })
        entry["缺陷数量"] = int(entry.get("缺陷数量") or 0) + 1
        # 缺陷登记视为缺陷类巡视结论，状态随之对账为「存在缺陷」。
        self._sync_status(entry)
        return entry, f"线路 {entry['线路编号']} 缺陷已登记（第 {entry['缺陷数量']} 项）"

    def _stop_line(
        self, entry: dict[str, Any], values: dict[str, Any], *, operator: str
    ) -> tuple[dict[str, Any] | None, str]:
        line_no = str(entry.get("线路编号") or "")
        # 收口第二步：申请停运只能由线路责任人本人提交，且必须写明停运原因。
        if operator != entry.get("责任人"):
            return None, (
                f"线路 {line_no} 的停运申请只能由责任人「{entry.get('责任人')}」提交，"
                f"当前操作人「{operator}」无权停运"
            )
        reason = str(values.get("停运原因") or "").strip()
        if not reason:
            return None, f"线路 {line_no} 申请停运必须写明停运原因"
        record_day = str(values.get("停运日期") or today_str()).strip()
        entry["巡视历史"].append({
            "日期": record_day,
            "类型": "停运",
            "巡视结论": STOPPED_STATUS,
            "说明": reason,
            "班组": entry.get("所属班组"),
            "提交人": operator,
        })
        entry["停运原因"] = reason
        entry["status"] = STOPPED_STATUS
        entry["pending"] = False
        entry["abnormal"] = False
        return entry, f"线路 {line_no} 已停运，停运原因已留档"

    def _change_owner(
        self, entry: dict[str, Any], values: dict[str, Any], *, team: str, operator: str
    ) -> tuple[dict[str, Any] | None, str]:
        new_owner = str(values.get("新责任人") or "").strip()
        new_team = str(values.get("新班组") or team).strip()
        if new_team not in TEAMS:
            return None, f"目标班组「{new_team}」不存在"
        if new_owner not in TEAMS[new_team]:
            return None, f"「{new_owner}」不是{new_team}成员，不能指定为线路责任人"
        old_owner = entry.get("责任人")
        old_team = entry.get("所属班组")
        if new_owner == old_owner and new_team == old_team:
            return None, "新责任人与当前责任人一致，无需变更"
        entry["巡视历史"].append({
            "日期": today_str(),
            "类型": "责任人变更",
            "巡视结论": entry.get("status"),
            "说明": f"责任人由 {old_team}/{old_owner} 变更为 {new_team}/{new_owner}（操作人 {operator}）",
            "班组": old_team,
            "提交人": operator,
        })
        entry["责任人"] = new_owner
        entry["所属班组"] = new_team
        # 历史巡视记录不做任何改写，仍归原班组。
        return entry, f"线路 {entry['线路编号']} 责任人已变更为 {new_team}/{new_owner}；历史巡视记录仍归原班组"

    # ---- 内部口径 ------------------------------------------------------
    def _sync_status(self, entry: dict[str, Any]) -> None:
        """以最近一次巡视/缺陷结论对账状态，保证责任归属与巡视结论一致。"""
        latest = next(
            (
                record for record in reversed(entry.get("巡视历史", []))
                if record.get("类型") in ("巡视", "缺陷登记")
            ),
            None,
        )
        if latest is None:
            status = PENDING_STATUS
        elif latest.get("巡视结论") == "存在缺陷":
            status = "存在缺陷"
        else:
            status = "运行正常"
        entry["status"] = status
        entry["pending"] = status == PENDING_STATUS
        entry["abnormal"] = status == "存在缺陷"

    @staticmethod
    def _parse_length(value: Any) -> float:
        try:
            return round(float(str(value).strip()), 2)
        except (TypeError, ValueError):
            return 0.0

    def _present(
        self,
        entry: dict[str, Any],
        *,
        team: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        """台账/明细/导出统一出口：起止杆塔与线路长度只此一种展示口径。"""
        # 读取时顺手对账，保证进入列表页看到的状态与巡视结论对得上。
        if entry.get("status") != STOPPED_STATUS:
            self._sync_status(entry)

        length_km = entry.get("线路长度km")
        length_text = f"{float(length_km):g} km" if isinstance(length_km, (int, float)) else "—"
        start = entry.get("起始杆塔")
        end = entry.get("终止杆塔")
        tower_span = f"{start}～{end}" if start and end else "—"

        owner_team = str(entry.get("所属班组") or "")
        is_owner_team = team is not None and team == owner_team
        is_stopped = entry.get("status") == STOPPED_STATUS
        view = {
            "id": entry["id"],
            "status": entry["status"],
            "线路编号": entry.get("线路编号"),
            "电压等级": entry.get("电压等级"),
            "所属场站": entry.get("所属场站"),
            "起止杆塔": tower_span,
            "线路长度": length_text,
            "所属班组": owner_team,
            "责任人": entry.get("责任人"),
            "上次巡视日": entry.get("上次巡视日"),
            "缺陷数量": entry.get("缺陷数量", 0),
            "线路状态": entry.get("status"),
            "停运原因": entry.get("停运原因"),
            "归属本班组": is_owner_team,
            # 停运线路在其它班组视图里只读；本班组停运期间同样冻结。
            "只读": (not is_owner_team) or is_stopped,
        }
        if operator is not None:
            view["可申请停运"] = is_owner_team and operator == entry.get("责任人") and not is_stopped
        return view
