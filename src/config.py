# Copyright (C) 2022-2026 CharlesWithC All rights reserved.
# Author: @CharlesWithC
#
# See /docs/config.jsonc for configuration instructions.

import json
import re
from enum import Enum
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, Field, HttpUrl, IPvAnyAddress, StringConstraints

from src.multilang import LANGUAGES
from src.static import TRACKER

'''
config.rank_types[].details[].bonus format
- \\* `min_distance`/`max_distance`: int
- \\*`probability`: float = 0~1
- \\* `type`: str = `fixed_value`/`fixed_percentage`/`random_value`/`random_percentage`
- `val`: int/float when `type` is `fixed_*`
- `min`/`max`: int/float when `type` is `random_*`

config.rank_types[].details[].daily_bonus format
- \\* `base`: int
- \\* `type`: str = `fixed`/`streak`
- `streak_type`: str = `fixed`/`percentage`/`algo` when `type` is `streak`
- `streak_value`: int when `streak_type` is `fixed` / float when `streak_type` is `percentage`/`algo` when `type` is `streak`
- `algo_offset`: positive float when `streak_type` is `algo`, controls the initial growth rate of the result
'''

BindPort = Annotated[int, Field(gt=0, le=65535)]
HexColor = Annotated[str, StringConstraints(to_lower=True, pattern=r"^[a-f0-9]{6}$")]

Language = Enum("Language", LANGUAGES)
Plugin = Literal["announcement", "application", "banner", "challenge", "division", "downloads", "economy", "event", "poll", "task", "route"]
Tracker = Literal["tracksim", "trucky", "custom", "unitracker"]
assert list(get_args(Tracker)) == list(TRACKER.keys()), "`Tracker` in `config.py` must match `TRACKER` in `static.py`"
DatabaseType = Literal["mysql"]
DistanceUnit = Literal["metric", "imperial"]
CaptchaProvider = Literal["hcaptcha", "cloudflare"]
AccountConnection = Literal["email", "discord", "steam", "truckersmp"]
BannerInfo = Literal["rank", "division", "division_first"]
DeliveryRuleAction = Literal["block", "drop", "bypass"]
RankPointType = Literal["distance", "challenge", "division", "event", "bonus"]
DistanceBonusType = Literal["fixed_value", "fixed_percentage", "random_value", "random_percentage"]
DailyBonusType = Literal["fixed", "streak"]
DailyBonusStreakType = Literal["fixed", "percentage", "algo"]
DivisionPointType = Literal["static", "ratio"]
TruckyRealisticSettings = Literal["bad_weather_factor", "detected", "detours", "fatigue", "fuel_similation", "hardcore_simulation", "hud_speed_limit", "parking_difficulty", "police", "road_events", "show_game_blockers", "simple_parking_doubles", "traffic_enabled", "trailer_advanced_coupling"]

class CaptchaConfig(BaseModel):
    # disable captcha with none values
    provider: CaptchaProvider | None = None
    secret: str | None = None

class FrontendUrls(BaseModel):
    member: HttpUrl
    delivery: HttpUrl
    email_confirm: HttpUrl

class EmailTemplates(BaseModel):
    class EmailTemplate(BaseModel):
        subject: str
        from_email: str
        html: str
        plain: str

    register: EmailTemplate | None = None
    update_email: EmailTemplate | None = None
    reset_password: EmailTemplate | None = None

class UserRole(BaseModel):
    id: int
    order_id: int
    name: str
    discord_role_id: str | None = None

class UserRank(BaseModel):
    class RankDetail(BaseModel):
        class DistanceBonus(BaseModel):
            min_distance: Annotated[int, Field(ge=0)]
            max_distance: Annotated[int, Field(ge=0)]
            probability: Annotated[float, Field(ge=0, le=1)] | None
            type: DistanceBonusType
            value: float | None # used when type=fixed_*
            value_min: float | None # used when type=random_*
            value_max: float | None # used when type=random_*

        class DailyBonus(BaseModel):
            base: int
            type: DailyBonusType
            streak_type: DailyBonusStreakType | None # used when type=streak
            streak_value: float | None # used when type=streak
            algo_offset: float | None # used when streak_type=algo

        points: int
        name: str
        color: HexColor | None = None
        discord_role_id: str | None = None
        distance_bonus: DistanceBonus | None = None
        daily_bonus: DailyBonus | None = None

    id: int = 1
    name: str = "Default"
    default: bool = True
    point_types: list[RankPointType] = ["distance", "challenge", "division", "event", "bonus"]
    details: list[RankDetail] = []

class JobTracker(BaseModel):
    type: Tracker
    company_id: str | None = None
    api_token: str | None = None
    webhook_secret: str | None = None
    ip_whitelist: list[IPvAnyAddress] = []

class DeliveryRules(BaseModel):
    # yes, negative values are intentionally allowed
    # but they could be quite nonsense anyway
    max_speed: int | None = None
    max_profit: int | None = None
    max_xp: int | None = None
    max_warp: int | None = None
    required_realistic_settings: list[TruckyRealisticSettings] = []
    action: DeliveryRuleAction = "block"

class BaseWebhook(BaseModel):
    channel_id: str | None = None
    webhook_url: str | None = None

class ContentWebhook(BaseWebhook):
    content: str = ""

class EmbedWebhook(ContentWebhook):
    embeds: list[dict] = [] # free-form dict for flexibility

class DiscordIntegration(BaseModel):
    class DeliveryLog(BaseWebhook):
        image_urls: list[HttpUrl] = []

    class AuditLog(BaseWebhook):
        category: list[str] = ["*"]

    class WebhookWithRoleChange(EmbedWebhook):
        role_change: list[str] = []

    guild_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    bot_token: str | None = None
    webhook_error: HttpUrl # all backend error

    sync_discord_email: bool = True
    must_join_guild: bool = True
    use_server_nickname: bool = True
    guild_message_regex_replace: dict[re.Pattern, re.Pattern] = {}

    delivery_log: DeliveryLog
    audit_log: list[AuditLog] = []

    member_accept: list[WebhookWithRoleChange] = []
    member_leave: list[WebhookWithRoleChange] = []
    driver_role_add: list[WebhookWithRoleChange] = []
    driver_role_remove: list[WebhookWithRoleChange] = []
    rank_up: list[EmbedWebhook] = []

class PluginAnnouncement(BaseModel):
    class AnnouncementType(BaseModel):
        id: int
        name: str
        staff_role_ids: list[int]

    class AnnouncementForward(EmbedWebhook):
        is_private: bool | None = None

    types: list[AnnouncementType] = []
    forwards: list[AnnouncementForward] = []

class PluginApplication(BaseModel):
    class ApplicationType(BaseModel):
        id: int
        name: str
        staff_role_ids: list[int] = []
        required_connections: list[AccountConnection] = []
        discord_role_changes: list[str] = []
        forwards: list[ContentWebhook] = []

        required_member_state: Annotated[int, Field(ge=-1, le=1)] = 0
        required_either_user_role_ids: list[int] = []
        required_all_user_role_ids: list[int] = []
        prohibited_either_user_role_ids: list[int] = []
        prohibited_all_user_role_ids: list[int] = []
        cooldown_hours: Annotated[int, Field(ge=0)] = 0
        allow_multiple_pending: bool = False

    types: list[ApplicationType] = []

class PluginChallenge(BaseModel):
    creation_forwards: list[EmbedWebhook] = []
    completion_forwards: list[EmbedWebhook] = []

class PluginDivision(BaseModel):
    class DivisionType(BaseModel):
        class DivisionBonus(BaseModel):
            mode: DivisionPointType = "static"
            value: float = 500

        id: int
        name: str
        bonus: DivisionBonus
        role_id: int
        staff_role_ids: list[int] = []
        validation_request_forwards: list[ContentWebhook] = []

    types: list[DivisionType] = []

class PluginDownloads(BaseModel):
    creation_forwards: list[EmbedWebhook] = []

class PluginEconomy(BaseModel):
    class EconomyTruck(BaseModel):
        id: str
        brand: str
        model: str
        price: int # yes, you can make it negative

    class EconomyGarage(BaseModel):
        id: str
        name: str
        x: float
        z: float
        price: int = 100000 # yes, you can make it negative
        base_slots: Annotated[int, Field(ge=0)] = 3
        slot_price: int = 50000 # yes, you can make it negative

    class EconomyMerch(BaseModel):
        id: str
        name: str
        buy_price: int # yes, you can make it negative
        sell_price: int # yes, you can make it negative

    trucks: list[EconomyTruck]
    garages: list[EconomyGarage]
    merch: list[EconomyMerch]

    truck_refund_pct: Annotated[float, Field(ge=0, le=1)] = 0.5
    scrap_refund_pct: Annotated[float, Field(ge=0, le=1)] = 0.1
    garage_refund_pct: Annotated[float, Field(ge=0, le=1)] = 0.8
    garage_slot_refund_pct: Annotated[float, Field(ge=0, le=1)] = 0.8

    currency_name: str = "coin"
    usd_to_currency: Annotated[float, Field(ge=0)] = 0.5
    eur_to_currency: Annotated[float, Field(ge=0)] = 0.6
    revenue_cut_pct: Annotated[float, Field(ge=0, le=1)] = 0.4
    truck_rental_cost: int = 5000 # yes, you can make it negative

    truck_wear_ratio: Annotated[float, Field(ge=0)] = 0.2
    max_wear_before_service: Annotated[float, Field(ge=0, le=1)] = 0.2
    max_distance_before_scrap: Annotated[int, Field(ge=0)] = 500000
    unit_service_price: int = 1200 # yes, you can make it negative

    allow_truck_purchase: bool = True
    allow_garage_purchase: bool = True
    allow_garage_slot_purchase: bool = True

    enable_balance_leaderboard: bool = True

class PluginEvent(BaseModel):
    class EventForward(EmbedWebhook):
        is_private: bool | None = None

    class EventUpcomingForward(EventForward):
        seconds_ahead: int = 0

    creation_forwards: list[EventForward] = []
    upcoming_forwards: list[EventUpcomingForward] = []

class PluginPoll(BaseModel):
    creation_forwards: list[EmbedWebhook] = []

class DHConfig(BaseModel):
    unique_id: Annotated[str, StringConstraints(to_lower=True, pattern=r"^[a-z0-9]+$")] # required
    org_name: str # required
    prefix: str = Field(default_factory=lambda data: "/" + data["unique_id"])
    plugins: list[Plugin] = list(get_args(Plugin))
    external_plugins: list[str] = []

    language: Language = "en"
    distance_unit: DistanceUnit = "metric"
    required_connections: list[AccountConnection] = ["discord", "steam"]
    register_methods: list[AccountConnection] = ["discord", "steam"]

    privacy: bool = False
    use_custom_activity: bool = False
    allow_custom_profile: bool = True
    security_level: Annotated[int, Field(ge=0, le=2)] = 1
    avatar_domain_whitelist: list[str] = ["charlws.com", "cdn.discordapp.com", "steamstatic.com"]
    ratelimit_whitelist: list[IPvAnyAddress] = []
    captcha: CaptchaConfig

    hex_color: HexColor = "ffffff"
    logo_url: HttpUrl # required
    banner_background_url: HttpUrl | None = None
    banner_background_opacity: Annotated[float, Field(ge=0, le=1)] = 0.15
    banner_info_first_row: BannerInfo = "rank"

    hostname_frontend: str # required
    hostname_backend: str # required
    frontend_urls: FrontendUrls = Field(default_factory=lambda data: FrontendUrls(member=f"https://{data['hostname_frontend']}/member?userid={{userid}}", delivery=f"https://{data['hostname_frontend']}/delivery?logid={{logid}}", email_confirm=f"https://{data['hostname_frontend']}/auth/email?secret={{secret}}"))

    bind_ip: IPvAnyAddress = "127.0.0.1"
    bind_port: BindPort = 7777
    server_workers: Annotated[int, Field(gt=0)] = 1
    swagger_ui: bool = False

    database_type: DatabaseType = "mysql"
    database_host: str = "localhost"
    database_port: BindPort = 3306
    database_username: str # required
    database_password: str # required
    database_schema: str = "drivershub"
    database_data_directory: str = "/var/lib/mysql/"
    database_connection_pool: Annotated[int, Field(gt=0)] = 10
    database_error_keywords: list[str] = ["lost connection", "deadlock", "readexactly", "timeout", "[aiosql]"]

    redis_host: str = "localhost"
    redis_port: BindPort = 6379
    redis_database: Annotated[int, Field(ge=0)] = 0
    redis_password: str | None = None

    smtp_host: str | None = None
    smtp_port: str | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    email_templates: EmailTemplates

    user_perms: dict[str, list[int]] = {} # perm: [role_id]
    user_roles: list[UserRole] = []
    user_ranks: list[UserRank] = []

    discord_integration: DiscordIntegration
    steam_api_key: str | None = None

    job_trackers: list[JobTracker] = []
    delivery_rules: DeliveryRules

    plugin_announcement: PluginAnnouncement
    plugin_application: PluginApplication
    plugin_challenge: PluginChallenge
    plugin_division: PluginDivision
    plugin_downloads: PluginDownloads
    plugin_economy: PluginEconomy
    plugin_event: PluginEvent
    plugin_poll: PluginPoll

def load_config(config_path: str) -> DHConfig:
    config_dict = json.loads(open(config_path, "r", encoding="utf-8").read())
    return DHConfig.model_validate(config_dict)

def validate_config(config_dict: dict) -> DHConfig:
    return DHConfig.model_validate(config_dict)

def dump_config(config: DHConfig) -> dict:
    return config.model_dump()

def dump_config_json(config: DHConfig) -> str:
    return config.model_dump_json(indent=4, ensure_ascii=False)
