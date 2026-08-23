# Copyright (C) 2022-2026 CharlesWithC All rights reserved.
# Author: @CharlesWithC
#
# This module should not be imported by any other module.
# It should only be dynamically loaded by uvicorn.
#
# If imported when env vars are not set, `createFullApp` will raise an error.

import copy
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

import src.api as api
import src.app as base
import src.db as db
import src.static as static
from src.app import DHApp
from src.functions.dataop import b64d


@asynccontextmanager
async def lifespan(app: FastAPI):
    for route in app.routes:
        if hasattr(route, "app") and hasattr(route, "name") and getattr(route, "name").endswith("Drivers Hub"):
            await api.startup_event(getattr(route, "app"))
    yield
    for route in app.routes:
        if hasattr(route, "app") and hasattr(route, "name") and getattr(route, "name").endswith("Drivers Hub"):
            await api.shutdown_event(getattr(route, "app"))
    os._exit(42)

def createFullApp():
    launch_args = json.loads(b64d(os.environ["LAUNCH_ARGS"]))
    config_paths = json.loads(b64d(os.environ["CONFIG_PATHS"]))
    openapi_path = os.environ["OPENAPI_PATH"]

    servers = []

    # create main application
    openapi_config = copy.deepcopy(static.OPENAPI)
    if openapi_path != "" and openapi_config is not None:
        app = DHApp(title = "Drivers Hub", version = static.version, lifespan=lifespan, \
                      openapi_url = f"{openapi_path.rstrip('/')}/openapi.json", docs_url = f"{openapi_path}", redoc_url=None)

        # set openapi
        def openapi() -> dict[str, object]:
            data = openapi_config
            data["servers"] = servers
            data["info"]["version"] = static.version
            return data
        app.openapi = openapi
    else:
        app = DHApp(title = "Drivers Hub", version = static.version, lifespan=lifespan)

    if launch_args["use_master_db_pool"]:
        app.db = db.aiosql(host = os.environ["MASTER_DB_HOST"], username = os.environ["MASTER_DB_USER"], password = os.environ["MASTER_DB_PASSWORD"], schema = 'information_schema', pool = int(os.environ['MASTER_DB_POOLSIZE']), master_db=True)
    else:
        app.db = None

    # mount drivers hub sub-applications
    for config_path in config_paths:
        dh = base.createApp(config_path, multi_mode = len(config_paths) > 1, dry_run = False, args = launch_args, master_db = app.db)
        if dh is not None:
            app.mount(f"{dh.config.prefix}", dh, name = f"{dh.config.name} Drivers Hub")
            servers.append({"url": f"https://{dh.config.domain}{dh.config.prefix}", "description": dh.config.name})

    return app
