"""User-owned folders for organizing backtest runs."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Request

from qbt_web import db
from qbt_web.auth import principal_from_request
from qbt_web.models import RunGroupCreate, RunGroupList, RunGroupOut, RunGroupUpdate

router = APIRouter(prefix="/api/run-groups")


def _clean_name(value: str) -> str:
    name = " ".join(value.split())
    if not name:
        raise HTTPException(status_code=400, detail="分组名称不能为空")
    return name


def _require_editable(group) -> None:
    if group.name == db.DEFAULT_RUN_GROUP_NAME:
        raise HTTPException(status_code=400, detail="默认分组不能重命名或删除")


def _require_admin(request: Request):
    principal = principal_from_request(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以管理全局分组")
    return principal


@router.get("", response_model=RunGroupList)
async def list_groups(request: Request):
    principal_from_request(request)
    return {"groups": db.list_run_groups()}


@router.post("", response_model=RunGroupOut, status_code=201)
async def create_group(payload: RunGroupCreate, request: Request):
    principal = _require_admin(request)
    try:
        return db.create_run_group(
            _clean_name(payload.name),
            owner_user_id=principal.user_id,
            owner_username=principal.username,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="已存在同名分组") from exc


@router.patch("/{group_id}", response_model=RunGroupOut)
async def update_group(group_id: int, payload: RunGroupUpdate, request: Request):
    _require_admin(request)
    group = db.get_run_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    _require_editable(group)
    try:
        db.rename_run_group(group_id, _clean_name(payload.name))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="已存在同名分组") from exc
    return db.get_run_group(group_id)


@router.delete("/{group_id}")
async def delete_group(group_id: int, request: Request):
    _require_admin(request)
    group = db.get_run_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    _require_editable(group)
    db.delete_run_group(group_id)
    return {"ok": True}
