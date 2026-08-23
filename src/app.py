# Copyright (C) 2022-2026 CharlesWithC All rights reserved.
# Author: @CharlesWithC

import copy
import functools
import importlib.util
import os
import time

import redis
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

import src.api as api
import src.apis as apis
import src.db as db
import src.plugins as plugins
import src.static as static
from src.config import DHConfig, UserRole, UserRank, RankPointType, \
                       PluginDivision, PluginEconomy, load_config
from src.db import aiosql
from src.functions.discord import opqueue
from src.logger import logger
from src.static import abspath, version


class PrefixedRedis:
    NO_KEY_METHODS = {"ping","info","time","client_list","client_setname","config_get","config_set","script_load","script_exists","pubsub","close","connection_pool"}
    EXEMPT_KEYS = {"session_errs"}

    def __init__(self, redis_instance, prefix):
        self.redis = redis_instance
        self.prefix = prefix

    def _prefix_key(self, key):
        if not isinstance(key, str) or key in PrefixedRedis.EXEMPT_KEYS:
            return key
        if key.startswith(self.prefix + ":"):
            logger.warning("[redis] Ignored duplicate prefix in key: %s", key)
            return key
        return f"{self.prefix}:{key}"

    def _wrap_client(self, client):
        def wrap_call(fn):
            @functools.wraps(fn)
            def inner(*args, **kwargs):
                if args:
                    args = (self._prefix_key(args[0]),) + args[1:]
                return fn(*args, **kwargs)
            return inner

        class Wrapper:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                if hasattr(client, "__exit__"):
                    return client.__exit__(exc_type, exc, tb)
                return False

            def __getattr__(self, name):
                attr = getattr(client, name)
                if not callable(attr) or name in PrefixedRedis.NO_KEY_METHODS:
                    return attr
                return wrap_call(attr)
        return Wrapper()

    def pipeline(self, *args, **kwargs):
        return self._wrap_client(self.redis.pipeline(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._wrap_client(self.redis), name)

class DHApp(FastAPI):
    config: DHConfig = None
    config_path: str = None
    config_last_modified: float = None
    loaded_external_plugins: list[str] = []
    external_middleware: dict[str, list] = {}
    banner_service_url: str = None

    db: aiosql | None = None
    use_master_db: bool = False

    redis: PrefixedRedis = None
    redis_bin: PrefixedRedis = None

    start_time: int = None
    multi_mode: bool = False
    enable_performance_header: bool = False
    memory_threshold: int = 0

    discord_op: opqueue = opqueue()

    # application-level config
    roles: dict[int, UserRole] = {}
    default_rank_type_point_types: list[RankPointType] = []
    rank_type_point_types: dict[int, list[RankPointType]] = {}
    ranks: dict[int, dict[int, UserRank.RankDetail]] = {}

    divisions: dict[int, PluginDivision.DivisionType] = {}
    division_role_ids: list[int] = []
    trucks: dict[str, PluginEconomy.EconomyTruck] = {}
    garages: dict[str, PluginEconomy.EconomyGarage] = {}
    merch: dict[str, PluginEconomy.EconomyMerch] = {}

def initApp(app: DHApp, first_init = False, args = {}):
    if not first_init:
        return app

    logger.info(f"[{app.config.unique_id}] Name: {app.config.org_name} | Prefix: {app.config.prefix}")
    if app.config.swagger_ui:
        logger.info(f"[{app.config.unique_id}] OpenAPI: Enabled")
    else:
        logger.info(f"[{app.config.unique_id}] OpenAPI: Disabled")
    if len(app.config.plugins) != 0:
        logger.info(f"[{app.config.unique_id}] Plugins: {', '.join(sorted(app.config.plugins))}")
    else:
        logger.info(f"[{app.config.unique_id}] Plugins: /")
    if len(app.config.external_plugins) != 0:
        extp = []
        for plugin_name in app.config.external_plugins:
            if plugin_name in app.loaded_external_plugins:
                extp.append(f"{plugin_name} (loaded)")
            else:
                extp.append(f"{plugin_name} (not loaded)")
        logger.info(f"[{app.config.unique_id}] External Plugins: {', '.join(sorted(extp))}")
    else:
        logger.info(f"[{app.config.unique_id}] External Plugins: /")

    if args["ignore_external_plugins"]:
        logger.warning(f"[{app.config.unique_id}] Ignoring external plugins")

    if app.use_master_db:
        logger.warning(f"[{app.config.unique_id}] Using master database pool")

    if app.enable_performance_header:
        logger.warning(f"[{app.config.unique_id}] Performance header enabled")
    if app.memory_threshold != 0:
        logger.warning(f"[{app.config.unique_id}] Memory threshold: {app.memory_threshold}MB (New requests will be put on hold when the threshold is reached)")

    if app.config.database_connection_pool < 5 and not app.use_master_db:
        logger.warning(f"[{app.config.unique_id}] Database pool size is smaller than 5, database error rate may increase")

    if "disable_upgrader" not in args or not args["disable_upgrader"]:
        import src.upgrades.manager as manager
        cur_version = app.version.replace(".dev", "").replace(".", "_")
        pre_version = cur_version.lstrip("v")
        conn = db.genconn(app.config)
        cur = conn.cursor()
        cur.execute("SELECT sval FROM settings WHERE skey = 'version'")
        t = cur.fetchall()
        cur.close()
        conn.close()
        if len(t) != 0:
            pre_version = t[0][0].replace(".dev", "").replace(".", "_").lstrip("v")
        if args.get("force_upgrade_from") is not None:
            pre_version = args["force_upgrade_from"]
            if pre_version not in manager.VERSION_CHAIN:
                logger.warning(f"[{app.config.unique_id}] Force upgrade version ({t[0][0]}) is not recognized. Aborted launch to prevent incompatability.")
                return None
        if pre_version != cur_version:
            if pre_version not in manager.VERSION_CHAIN:
                logger.warning(f"[{app.config.unique_id}] Previous version ({t[0][0]}) is not recognized. Aborted launch to prevent incompatability.")
                return None
            pre_idx = manager.VERSION_CHAIN.index(pre_version)
            if cur_version not in manager.VERSION_CHAIN:
                logger.warning(f"[{app.config.unique_id}] Current version ({version}) is not recognized. Aborted launch to prevent incompatability.")
                return None
            cur_idx = manager.VERSION_CHAIN.index(cur_version)
            for idx in range(pre_idx + 1, cur_idx + 1):
                v = manager.VERSION_CHAIN[idx]
                if v in manager.UPGRADER:
                    logger.info(f"[{app.config.unique_id}] Updating data to be compatible with {v.replace('_', '.')}...")
                    manager.UPGRADER[v].run(app)
        manager.unload()
    else:
        logger.warning(f"[{app.config.unique_id}] Upgrader disabled")

    conn = db.genconn(app.config)
    cur = conn.cursor()
    app.redis.delete("multiprocess-pid")
    app.redis.set("running_export", 0)
    app.redis.delete("avgrt:value")
    app.redis.delete("avgrt:counter")
    app.redis.delete("avgrt:reset-time")
    if not version.endswith(".dev"):
        cur.execute(f"UPDATE settings SET sval = '{version}' WHERE skey = 'version'")
    conn.commit()
    cur.close()
    conn.close()

    return app

# dry_run is used by main to validate the config
# logging is enabled only when dry_run=True
def createApp(config_path, multi_mode = False, dry_run = False, args = {}, master_db = None):
    if not os.path.exists(config_path):
        if dry_run:
            logger.error(f"Config file '{config_path}' not found.")
        return None

    try:
        config = load_config(config_path)
    except ValidationError as e:
        if dry_run:
            logger.error(f"Unable to parse config file '{config_path}': {e}")
        return None

    openapi_config = copy.deepcopy(static.OPENAPI)
    if config.swagger_ui and openapi_config is not None:
        app = DHApp(title="Drivers Hub", version=version, openapi_url="/doc/openapi.json", docs_url="/doc", redoc_url=None)
        def openapi() -> dict[str, object]:
            data = openapi_config
            data["servers"] = [{"url": f"https://{config.hostname_frontend}{config.prefix}", "description": config.org_name}]
            data["info"]["version"] = version
            return data
        app.openapi = openapi
    else:
        app = DHApp(title="Drivers Hub", version=version)

    # TODO: Properly define an `app` class that extends FastAPI
    app.config = config
    # TODO: REMOVE USE OF app.config_dict
    # app.config_dict = config_dict
    app.config_path = config_path
    app.config_last_modified = os.path.getmtime(app.config_path)
    app.start_time = int(time.time())
    app.multi_mode = multi_mode
    app.use_master_db = True if master_db else False
    if master_db:
        # use the database pool from the master app
        # this happens when --use-master-db-pool is enabled
        app.db = master_db
    else:
        # create individual database pool
        app.db = db.aiosql(host = app.config.database_host, username = app.config.database_username, password = app.config.database_password, schema = app.config.database_schema, pool_size = app.config.database_connection_pool)
    app.enable_performance_header = "enable_performance_header" in args and args["enable_performance_header"]
    app.memory_threshold = args["memory_threshold"] if "memory_threshold" in args else 0
    app.banner_service_url = args["banner_service_url"]

    app.redis = PrefixedRedis(redis.Redis(app.config.redis_host, app.config.redis_port, app.config.redis_database, app.config.redis_password, decode_responses = True), app.config.unique_id)
    app.redis_bin = PrefixedRedis(redis.Redis(app.config.redis_host, app.config.redis_port, app.config.redis_database, app.config.redis_password, decode_responses = False), app.config.unique_id)
    # auth:{authorization_key} | uinfo:{uid} | ulang:{uid} | utz:{uid} (timezone)
    # uprivacy:{uid} | unote:{from_uid}/{to_uid} | uactivity:{uid}
    # ratelimit:{identifier}(:{route}) => this is a set
    # stats:{rid}:{userid} | stats:after | stats:before
    # lb:{rid}:{speed_limit}:{game} | lb:after | lb:before | nlb

    # NOTE: In uinfo, userid is -1 if not exist, discordid/steamid/truckersmpid/email would be "" if not exist.
    # When extracting data, userid should be kept -1 unless returned in API response (converted to None),
    # discordid/steamid/truckersmpid should be handled by "nint" which converts "" to None,
    # email should be checked specially and converted to None if invalid.

    # for all redis objects with partial update, do extend expiry before accessing resource
    # if unsure about when the data expires or if data exists, do full update only
    # currently, we have partial update for: auth, uinfo

    # External routes must be loaded before internal routes so that they can replace internal routes (if needed)
    if args["ignore_external_plugins"]:
        app.config.external_plugins = []
    external_routes = []
    app.loaded_external_plugins = []
    app.external_middleware = {"startup": [], "request": [], "response_ok": [], "response_fail": [], "error_handler": [], "discord_request": []}
    for plugin_name in app.config.external_plugins:
        if os.path.exists(f"external_plugins/{plugin_name}.py"):
            spec = importlib.util.spec_from_file_location(plugin_name, os.path.join(os.path.join(abspath, "external_plugins"), plugin_name + ".py"))
            external_plugin = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(external_plugin)
        else:
            if dry_run:
                logger.warning(f"[{app.config.unique_id}] [External Plugin] Unable to load external plugin '{plugin_name}': File not found.")
            continue

        # init external plugin
        try:
            # TODO: Update external plugin example and core external plugins on use of class-based config
            res = external_plugin.init(app.config, dry_run)
            if res is False:
                if dry_run:
                    logger.warning(f"[{app.config.unique_id}] [External Plugin] '{plugin_name}' is not loaded: 'init' function did not return True.")
                continue
            routes = res[1]
            states = res[2]
            middlewares = res[3]
        except Exception as exc:
            if dry_run:
                logger.warning(f"[{app.config.unique_id}] [External Plugin] Unable to load external plugin '{plugin_name}': {exc}")
            continue

        # test routes and state
        try:
            test_app = DHApp()
            test_app.external_middleware = {"startup": [], "request": [], "response_ok": [], "response_fail": [], "error_handler": [], "discord_request": []}
            for route in routes:
                test_app.add_api_route(path=route.path, endpoint=route.endpoint, methods=route.methods, response_class=route.response_class)
            for state in states:
                if state not in app.state.__dict__:
                    test_app.state.__dict__[state] = states[state]
            for middleware_type in middlewares:
                if middleware_type in test_app.external_middleware:
                    middleware = middlewares[middleware_type]
                    if callable(middleware):
                        test_app.external_middleware[middleware_type].append(middleware)
                    elif type(middleware) == list:
                        for mdw in middleware:
                            if callable(mdw):
                                test_app.external_middleware[middleware_type].append(mdw)
        except Exception as exc:
            if dry_run:
                logger.warning(f"[{app.config.unique_id}] [External Plugin] Unable to load external plugin '{plugin_name}': {exc}")
            continue

        # load routes and state
        try:
            for route in routes:
                app.add_api_route(path=route.path, endpoint=route.endpoint, methods=route.methods, response_class=route.response_class)
                external_routes.append(route.path)
            for state in states:
                if state not in app.state.__dict__:
                    app.state.__dict__[state] = states[state]
            for middleware_type in middlewares:
                if middleware_type in app.external_middleware:
                    middleware = middlewares[middleware_type]
                    if callable(middleware):
                        app.external_middleware[middleware_type].append(middleware)
                    elif type(middleware) == list:
                        for mdw in middleware:
                            if callable(mdw):
                                app.external_middleware[middleware_type].append(mdw)
        except Exception as exc:
            if dry_run:
                logger.warning(f"[{app.config.unique_id}] [External Plugin] Unable to load external plugin '{plugin_name}': {exc}")
            continue

        app.loaded_external_plugins.append(plugin_name)

    routes = apis.routes + apis.auth.routes + apis.dlog.routes + apis.member.routes + apis.user.routes

    # both trackers will be added and 404 will be handled within the route
    # so we can realize switching tracker without needing to restart program
    routes += apis.tracker.routes_tracksim
    routes += apis.tracker.routes_trucky
    routes += apis.tracker.routes_custom
    routes += apis.tracker.routes_unitracker
    if "route" in app.config.plugins:
        routes += apis.tracker.routes_tracksim_route

    if "banner" in app.config.plugins:
        routes += apis.member.routes_banner
    if "announcement" in app.config.plugins:
        routes += plugins.routes_announcement
    if "application" in app.config.plugins:
        routes += plugins.routes_application
    if "challenge" in app.config.plugins:
        routes += plugins.routes_challenge
    if "division" in app.config.plugins:
        routes += plugins.routes_division
    if "downloads" in app.config.plugins:
        routes += plugins.routes_downloads
    if "economy" in app.config.plugins:
        routes += plugins.routes_economy
    if "event" in app.config.plugins:
        routes += plugins.routes_event
    if "poll" in app.config.plugins:
        routes += plugins.routes_poll
    if "task" in app.config.plugins:
        routes += plugins.routes_task
    for route in routes:
        if route.path not in external_routes:
            if multi_mode and route.path == "/restart":
                continue
            app.add_api_route(path=route.path, endpoint=route.endpoint, methods=route.methods, response_class=route.response_class)

    app.add_exception_handler(StarletteHTTPException, api.errorHandler)
    app.add_exception_handler(RequestValidationError, api.error422Handler)
    app.add_middleware(api.HubMiddleware)
    app.add_middleware(GZipMiddleware)

    app = static.load(app)

    app.state.dberr = [] # must be local since db pool is created locally
    # session_errs was moved to redis to prevent duplicate report
    app.state.discord_message_queue = []
    app.state.discord_retry_after = {}
    app.state.discord_opqueue = []
    app.state.statistics_details_last_work = -1 # be local since it's not THAT cpu intensive like dlog export

    try:
        if os.path.exists(f"/tmp/hub/logo/{app.config.unique_id}.png"):
            os.remove(f"/tmp/hub/logo/{app.config.unique_id}.png")
        if os.path.exists(f"/tmp/hub/logo/{app.config.unique_id}_bg.png"):
            os.remove(f"/tmp/hub/logo/{app.config.unique_id}_bg.png")
        if os.path.exists(f"/tmp/hub/template/{app.config.unique_id}.png"):
            os.remove(f"/tmp/hub/template/{app.config.unique_id}.png")
    except:
        pass

    try:
        app = initApp(app, first_init = dry_run, args = args)
    except Exception as exc:
        if dry_run:
            import traceback
            traceback.print_exc()
            logger.error(f"[{app.config.unique_id}] Error initializing app: {exc}")
        return None

    if dry_run and "rebuild_dlog_stats" in args and args["rebuild_dlog_stats"]:
        logger.warning(f"[{app.config.unique_id}] Rebuilding dlog stats, this might take some time...")
        apis.dlog.statistics.rebuild(app)

    return app
