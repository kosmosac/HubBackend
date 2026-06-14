# Copyright (C) 2022-2026 CharlesWithC All rights reserved.
# Author: @CharlesWithC

import json
import math
import os
import threading
import time
import traceback

from fastapi import Header, Request, Response
from pydantic import ValidationError

import src.multilang as ml
import src.static as static
from src.api import tracebackHandler
from src.app import DHApp
from src.config import load_config, validate_config, dump_config_json
from src.functions import *
from src.logger import logger

public_config_whitelist = ['name', 'language', 'distance_unit', 'privacy', 'hex_color', 'logo_url', 'banner_background_url', 'banner_info_first_row', 'plugins', 'sync_discord_email', 'must_join_guild', 'use_server_nickname', 'allow_custom_profile', 'use_custom_activity', 'discord_guild_id', 'discord_client_id', 'avatar_domain_whitelist', 'trackers', 'required_connections', 'register_methods']

class Dict2Obj(object):
    def __init__(self, d):
        for key in d:
            if type(d[key]) is dict:
                data = Dict2Obj(d[key])
                setattr(self, key, data)
            else:
                setattr(self, key, d[key])

async def post_discord_role_connection_enable(request: Request, response: Response, authorization: str | None = Header(None)):
    """Enable Discord Role Connection"""
    app: DHApp = request.app
    dhrid = request.state.dhrid
    rl = await ratelimit(request, 'POST /discord/role-connection/enable', 60, 5)
    if rl[0]:
        return rl[1]
    for k in rl[1]:
        response.headers[k] = rl[1][k]

    await app.db.new_conn(dhrid, db_name = app.config.db_name)

    au = await auth(authorization, request, required_permission = ["administrator"])
    if au["error"]:
        response.status_code = au["code"]
        del au["code"]
        return au

    headers = {"Authorization": f"Bot {app.config.discord_bot_token}", "Content-Type": "application/json"}
    try:
        r = await arequests.put(app, f"https://discord.com/api/v10/applications/{app.config.discord_client_id}/role-connections/metadata", data = json.dumps([{"type": 2, "key": "dlog", "name": "Deliveries", "description": "Deliveries submitted", "name_localizations": {"es-ES": "Entregas"}}, {"type": 2, "key": "distance", "name": "Distance(km)", "description": "Distance(km) driven", "name_localizations": {"es-ES": "Distancia(km)"}}, {"type": 7, "key": "is_driver", "name": "Driver", "description": "Must be a driver", "name_localizations": {"es-ES": "Conductor"}}, {"type": 6, "key": "member_since", "name": "Member Since", "description": "Days since creating an account", "name_localizations": {"es-ES": "Miembro Desde"}}]), headers = headers, dhrid = dhrid)
        if r.status_code // 100 != 2:
            response.status_code = 503
            return {"error": ml.tr(request, "discord_api_inaccessible", force_lang = au["language"])}
        return Response(status_code=204)
    except:
        response.status_code = 503
        return {"error": ml.tr(request, "discord_api_inaccessible", force_lang = au["language"])}

async def post_discord_role_connection_disable(request: Request, response: Response, authorization: str | None = Header(None)):
    """Disable Discord Role Connection"""
    app: DHApp = request.app
    dhrid = request.state.dhrid
    rl = await ratelimit(request, 'POST /discord/role-connection/disable', 60, 5)
    if rl[0]:
        return rl[1]
    for k in rl[1]:
        response.headers[k] = rl[1][k]

    await app.db.new_conn(dhrid, db_name = app.config.db_name)

    au = await auth(authorization, request, required_permission = ["administrator"])
    if au["error"]:
        response.status_code = au["code"]
        del au["code"]
        return au

    headers = {"Authorization": f"Bot {app.config.discord_bot_token}", "Content-Type": "application/json"}
    try:
        r = await arequests.put(app, f"https://discord.com/api/v10/applications/{app.config.discord_client_id}/role-connections/metadata", data = json.dumps([]), headers = headers, dhrid = dhrid)
        if r.status_code // 100 != 2:
            response.status_code = 503
            return {"error": ml.tr(request, "discord_api_inaccessible", force_lang = au["language"])}
        return Response(status_code=204)
    except:
        response.status_code = 503
        return {"error": ml.tr(request, "discord_api_inaccessible", force_lang = au["language"])}

async def get_config(request: Request, response: Response, authorization: str | None = Header(None)):
    """Returns saved config (config) and loaded config (backup)"""
    app: DHApp = request.app
    dhrid = request.state.dhrid
    rl = await ratelimit(request, 'GET /config', 60, 120)
    if rl[0]:
        return rl[1]
    for k in rl[1]:
        response.headers[k] = rl[1][k]

    await app.db.new_conn(dhrid, db_name = app.config.database_schema)

    permOk = False
    if authorization is not None:
        au = await auth(authorization, request, check_member = False, allow_application_token = True)
        if au["error"]:
            response.status_code = au["code"]
            del au["code"]
            return au
        permOk = checkPerm(app, au["roles"], ["administrator", "update_config"])

    if not permOk:
        cfg = app.config.model_dump_json()

        for key in cfg:
            if key not in public_config_whitelist:
                del cfg[key]
            if key == "trackers":
                cfg[key] = [{"type": tracker["type"], "company_id": tracker["company_id"]} for tracker in cfg[key]]

        return {"config": cfg}

    # possibly modified config that is saved but not reloaded
    last_modified = 0
    try:
        if os.path.exists(app.config_path + ".saved"):
            modcfg = load_config(app.config_path + ".saved")
            last_modified = os.path.getmtime(app.config_path + ".saved")
        else:
            modcfg = load_config(app.config_path, "r", encoding="utf-8"))
            last_modified = os.path.getmtime(app.config_path)
    except Exception as exc:
        await tracebackHandler(request, exc, traceback.format_exc())

    return {"pending": modcfg.model_dump_json(), "current": app.config.model_dump_json(), "pending_last_modified": int(last_modified), "current_last_modified": int(app.config_last_modified)}

def restart(app):
    time.sleep(3)
    os.system(f"nohup ./launcher hub restart {app.config.abbr} > /dev/null") # pyright: ignore[reportDeprecated]

async def patch_config(request: Request, response: Response, authorization: str | None = Header(None)):
    """Updates the config, only those specified in `config` will be updated

    JSON: `{"config": {}}`"""
    app = request.app
    dhrid = request.state.dhrid
    rl = await ratelimit(request, 'PATCH /config', 60, 60)
    if rl[0]:
        return rl[1]
    for k in rl[1]:
        response.headers[k] = rl[1][k]

    await app.db.new_conn(dhrid, db_name = app.config.db_name)

    au = await auth(authorization, request, required_permission = ["administrator", "update_config"])
    if au["error"]:
        response.status_code = au["code"]
        del au["code"]
        return au
    userroles = au["roles"]

    data = await request.json()
    try:
        # newcfg may not contain all keys; thus patch modcfg based on newcfg
        newcfg = data["config"]
        if type(data["config"]) != dict:
            response.status_code = 400
            return {"error": ml.tr(request, "bad_json", force_lang = au["language"])}
    except:
        response.status_code = 400
        return {"error": ml.tr(request, "bad_json", force_lang = au["language"])}

    if os.path.exists(app.config_path + ".saved"):
        modcfg = load_config(app.config_path + ".saved")
    else:
        modcfg = load_config(app.config_path)

    for tt in newcfg:
        if tt == "user_perms":
            newperms = newcfg[tt]
            if 'administrator' not in newperms:
                response.status_code = 400
                return {"error": ml.tr(request, "config_invalid_permission_admin_not_found", force_lang = au["language"])}
            perm_roles = intify(newperms["administrator"])
            ok = False
            for role in userroles:
                if role in perm_roles:
                    ok = True
            if not ok:
                response.status_code = 400
                return {"error": ml.tr(request, "config_invalid_permission_admin_protection", force_lang = au["language"])}

        modcfg[tt] = newcfg[tt]

    try:
        modcfg = validate_config(modcfg)
    except ValidationError as e:
        response.status_code = 400
        return {"error": str(e)}
    out = dump_config_json(modcfg)
    if len(out) > 512000:
        response.status_code = 400
        return {"error": ml.tr(request, "content_too_long", var = {"item": "config", "limit": "512,000"}, force_lang = au["language"])}
    # write to .saved until reload
    open(app.config_path + ".saved", "w", encoding="utf-8").write(out)

    await AuditLog(request, au["uid"], "system", ml.ctr(request, "updated_config"))

    return Response(status_code=204)

async def post_config_reload(request: Request, response: Response, authorization: str | None = Header(None)):
    """Reloads config, returns 204"""
    app = request.app
    dhrid = request.state.dhrid
    rl = await ratelimit(request, 'POST /config/reload', 60, 10)
    if rl[0]:
        return rl[1]
    for k in rl[1]:
        response.headers[k] = rl[1][k]

    await app.db.new_conn(dhrid, db_name = app.config.db_name)

    au = await auth(authorization, request, required_permission = ["administrator", "reload_config"])
    if au["error"]:
        response.status_code = au["code"]
        del au["code"]
        return au

    await app.db.execute(dhrid, f"SELECT mfa_secret FROM user WHERE userid = {au['userid']}")
    t = await app.db.fetchall(dhrid)
    mfa_secret = t[0][0]
    if mfa_secret == "":
        response.status_code = 428
        return {"error": ml.tr(request, "mfa_required", force_lang = au["language"])}

    data = await request.json()
    try:
        otp = data["otp"]
    except:
        response.status_code = 400
        return {"error": ml.tr(request, "invalid_otp", force_lang = au["language"])}
    if not valid_totp(otp, mfa_secret):
        response.status_code = 400
        return {"error": ml.tr(request, "invalid_otp", force_lang = au["language"])}

    await AuditLog(request, au["uid"], "system", ml.ctr(request, "reloaded_config"))

    if not os.path.exists(app.config_path + ".saved"):
        response.status_code = 428
        return {"error": ml.tr(request, "no_config_reload_available", force_lang = au["language"])}

    try:
        config = load_config(app.config_path + ".saved")
    except ValidationError as e:
        response.status_code = 400
        return {"error": str(e)}

    os.replace(app.config_path + ".saved", app.config_path)
    app.config = config
    app.config_last_modified = os.path.getmtime(app.config_path)
    logger.info(f"[{app.config.abbr}] [PID: {os.getpid()}] Config modification detected, reloaded config.")

    # TODO: This method should belong to app.py
    app = static.load(app)

    try:
        if os.path.exists(f"/tmp/hub/logo/{app.config.abbr}.png"):
            os.remove(f"/tmp/hub/logo/{app.config.abbr}.png")
        if os.path.exists(f"/tmp/hub/logo/{app.config.abbr}_bg.png"):
            os.remove(f"/tmp/hub/logo/{app.config.abbr}_bg.png")
        if os.path.exists(f"/tmp/hub/template/{app.config.abbr}.png"):
            os.remove(f"/tmp/hub/template/{app.config.abbr}.png")
    except:
        pass

    return Response(status_code=204)

async def post_restart(request: Request, response: Response, authorization: str | None = Header(None)):
    """Restarts API service in a thread, returns 204"""
    app = request.app
    dhrid = request.state.dhrid
    rl = await ratelimit(request, 'POST /restart', 600, 3)
    if rl[0]:
        return rl[1]
    for k in rl[1]:
        response.headers[k] = rl[1][k]

    await app.db.new_conn(dhrid, db_name = app.config.db_name)

    au = await auth(authorization, request, required_permission = ["administrator", "restart_service"])
    if au["error"]:
        response.status_code = au["code"]
        del au["code"]
        return au

    await app.db.execute(dhrid, f"SELECT mfa_secret FROM user WHERE userid = {au['userid']}")
    t = await app.db.fetchall(dhrid)
    mfa_secret = t[0][0]
    if mfa_secret == "":
        response.status_code = 428
        return {"error": ml.tr(request, "mfa_required", force_lang = au["language"])}

    data = await request.json()
    try:
        otp = data["otp"]
    except:
        response.status_code = 400
        return {"error": ml.tr(request, "invalid_otp", force_lang = au["language"])}
    if not valid_totp(otp, mfa_secret):
        response.status_code = 400
        return {"error": ml.tr(request, "invalid_otp", force_lang = au["language"])}

    if os.path.exists(app.config_path + ".saved"):
        try:
            config = load_config(app.config_path + ".saved")
        except ValidationError as e:
            response.status_code = 400
            return {"error": str(e)}

        os.replace(app.config_path + ".saved", app.config_path)
        app.config = config
        app.config_last_modified = os.path.getmtime(app.config_path)
        logger.info(f"[{app.config.abbr}] [PID: {os.getpid()}] Config modification detected, reloaded config.")

        # TODO: This method should belong to app.py
        app = static.load(app)

    try:
        if os.path.exists(f"/tmp/hub/logo/{app.config.abbr}.png"):
            os.remove(f"/tmp/hub/logo/{app.config.abbr}.png")
        if os.path.exists(f"/tmp/hub/logo/{app.config.abbr}_bg.png"):
            os.remove(f"/tmp/hub/logo/{app.config.abbr}_bg.png")
    except:
        pass

    await AuditLog(request, au["uid"], "system", ml.ctr(request, "restarted_service"))

    threading.Thread(target=restart, args=(app,)).start()

    return Response(status_code=204)

async def get_audit_list(request: Request, response: Response, authorization: str | None = Header(None), \
    page: int | None = 1, page_size: int | None = 30, order: str | None = "desc", after: int | None = None, before: int | None = None, uid: int | None = None, operation: str | None = "", category: str | None = None):
    """Returns a list of audit log

    `category` could be a list of categories separated by comma"""
    app = request.app
    dhrid = request.state.dhrid
    rl = await ratelimit(request, 'GET /audit/list', 60, 120)
    if rl[0]:
        return rl[1]
    for k in rl[1]:
        response.headers[k] = rl[1][k]

    await app.db.new_conn(dhrid, db_name = app.config.db_name)

    au = await auth(authorization, request, required_permission = ["administrator", "view_audit_log"])
    if au["error"]:
        response.status_code = au["code"]
        del au["code"]
        return au

    operation = convertQuotation(operation.lower())

    category_query = ""
    if category is not None:
        category = convertQuotation(category.lower())
        category = [x.strip() for x in category.split(",")]
        category_query = "AND category in (" + ",".join([f"'{x}'" for x in category]) + ")"

    if page < 1:
        response.status_code = 400
        return {"error": ml.tr(request, "invalid_value", var = {"key": "page"})}
    if page_size < 1 or page_size > 500:
        response.status_code = 400
        return {"error": ml.tr(request, "invalid_value", var = {"key": "page_size"})}

    order = order.lower()
    if order not in ["asc", "desc"]:
        response.status_code = 400
        return {"error": ml.tr(request, "invalid_value", var = {"key": "order"})}

    limit = ""
    if uid is not None:
        limit = f"AND uid = {uid} "
    if after is not None:
        limit += f"AND timestamp >= {after} "
    if before is not None:
        limit += f"AND timestamp <= {before} "

    await app.db.execute(dhrid, f"SELECT * FROM auditlog WHERE LOWER(operation) LIKE '%{operation}%' {limit} {category_query} ORDER BY timestamp {order.upper()} LIMIT {max(page-1, 0) * page_size}, {page_size}")
    t = await app.db.fetchall(dhrid)
    ret = []
    for tt in t:
        ret.append({"user": await GetUserInfo(request, uid = tt[0]), "category": tt[1], "operation": tt[2], "timestamp": tt[3]})

    await app.db.execute(dhrid, f"SELECT COUNT(*) FROM auditlog WHERE LOWER(operation) LIKE '%{operation}%' {limit} {category_query}")
    t = await app.db.fetchall(dhrid)
    tot = t[0][0]

    return {"list": ret, "total_items": tot, "total_pages": int(math.ceil(tot / page_size))}
