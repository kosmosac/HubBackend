# Copyright (C) 2022-2026 CharlesWithC All rights reserved.
# Author: @CharlesWithC

from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

import src.apis.admin as admin
import src.apis.info as info
import src.apis.auth as auth
import src.apis.dlog as dlog
import src.apis.member as member
import src.apis.tracker as tracker
import src.apis.user as user

__all__ = ["auth", "dlog", "member", "tracker", "user"]

routes = [
    APIRoute("/", info.get_index, methods=["GET"], response_class=JSONResponse),
    APIRoute("/status", info.get_status, methods=["GET"], response_class=JSONResponse),
    APIRoute("/status/database/restart", info.restart_database, methods=["POST"], response_class=JSONResponse),
    APIRoute("/languages", info.get_languages, methods=["GET"], response_class=JSONResponse),

    APIRoute("/discord/role-connection/enable", admin.post_discord_role_connection_enable, methods=["POST"], response_class=JSONResponse),
    APIRoute("/discord/role-connection/disable", admin.post_discord_role_connection_disable, methods=["POST"], response_class=JSONResponse),

    APIRoute("/config", admin.get_config, methods=["GET"], response_class=JSONResponse),
    APIRoute("/config", admin.patch_config, methods=["PATCH"], response_class=JSONResponse),
    APIRoute("/config/reload", admin.post_config_reload, methods=["POST"], response_class=JSONResponse),
    APIRoute("/restart", admin.post_restart, methods=["POST"], response_class=JSONResponse),
    APIRoute("/audit/list", admin.get_audit_list, methods=["GET"], response_class=JSONResponse)
]
