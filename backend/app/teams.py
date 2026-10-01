"""班组与人员口径：集电线路按「所属班组」收口，名单是权限判断的唯一来源。

真实项目里这部分来自组织架构服务；当前用静态名单保证开箱可演示。
"""
from __future__ import annotations

# 班组 -> 班组成员（线路责任人必须出自该名单）
TEAMS: dict[str, dict[str, list[str]]] = {
    "集电一班": {"members": ["张建国", "李文斌", "王海燕"]},
    "集电二班": {"members": ["赵启明", "孙丽华", "周立军"]},
    "升压站运维班": {"members": ["吴海涛", "郑晓峰"]},
}

# 管理员不属于任何运维班组：只能查看与变更责任人，不能代班提交巡视/缺陷/停运
ADMIN_NAME = "值班管理员"


def teams_payload() -> dict[str, object]:
    """给前端的班组/人员下拉数据。"""
    return {
        "teams": [
            {"name": name, "members": list(meta["members"])}
            for name, meta in TEAMS.items()
        ],
        "admin": ADMIN_NAME,
    }


def is_member(team: str, operator: str) -> bool:
    """操作人是否在指定班组的成员名单内。"""
    return operator in TEAMS.get(team, {}).get("members", [])
