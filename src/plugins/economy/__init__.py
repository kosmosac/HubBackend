# Copyright (C) 2022-2026 CharlesWithC All rights reserved.
# Author: @CharlesWithC

from src.functions import *
from src.plugins.economy.balance import *
from src.plugins.economy.garages import *
from src.plugins.economy.merch import *
from src.plugins.economy.trucks import *

# NOTE
# If driver leaves the company, they'll take away their truck and balance.
# However, their garage will be transferred to the company.

async def get_economy(request: Request, response: Response, authorization: str | None = Header(None)):
    app: DHApp = request.app
    dhrid = request.state.dhrid
    rl = await ratelimit(request, 'GET /economy', 60, 60)
    if rl[0]:
        return rl[1]
    for k in rl[1]:
        response.headers[k] = rl[1][k]

    await app.db.new_conn(dhrid, db_name = app.config.database_schema)

    au = await auth(authorization, request, allow_application_token = True)
    if au["error"]:
        response.status_code = au["code"]
        del au["code"]
        return au

    ret = app.config.plugin_economy.model_dump()
    del ret["trucks"]
    del ret["garages"]
    del ret["merch"]
    return ret
