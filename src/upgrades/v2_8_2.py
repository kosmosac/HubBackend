# Copyright (C) 2022-2026 CharlesWithC All rights reserved.
# Author: @CharlesWithC

# This upgrade adds the "tracker_in_use" column to "user" table
# And set the default value based on the "tracker" in app.config

from src.db import genconn
from src.logger import logger


def run(app):
    conn = genconn(app.config, autocommit = True)
    cur = conn.cursor()

    try:
        cur.execute("SELECT tracker_in_use FROM user LIMIT 1")
    except:
        logger.info("Updating user TABLE")
        cur.execute("ALTER TABLE user ADD tracker_in_use INT AFTER mfa_secret")
        cur.execute("UPDATE user SET tracker_in_use = 0") # set a default value first
        if type(app.config_old.trackers) == str:
            # config not updated yet
            if app.config_old.trackers == "tracksim":
                cur.execute("UPDATE user SET tracker_in_use = 2 WHERE userid >= 0")
            elif app.config_old.trackers == "trucky":
                cur.execute("UPDATE user SET tracker_in_use = 3 WHERE userid >= 0")
        elif type(app.config_old.trackers) == list and len(app.config_old.trackers) > 0:
            # config already updated, then we'll consider the first tracker
            if app.config_old.trackers[0]["type"] == "tracksim":
                cur.execute("UPDATE user SET tracker_in_use = 2 WHERE userid >= 0")
            elif app.config_old.trackers[0]["type"] == "trucky":
                cur.execute("UPDATE user SET tracker_in_use = 3 WHERE userid >= 0")

    cur.close()
    conn.close()

    logger.info("Upgrade finished")
