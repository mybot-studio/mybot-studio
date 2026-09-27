from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

# Auth
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

# Bot Management
class BotCreateRequest(BaseModel):
    token: str
    custom_proxy: Optional[str] = None
    cf_worker_url: Optional[str] = None

class BotSettingsUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    token: Optional[str] = None
    bio: Optional[str] = None
    description: Optional[str] = None
    is_miniapp_enabled: Optional[bool] = None
    miniapp_url: Optional[str] = None
    auto_chat_action: Optional[bool] = None
    typing_delay_ms: Optional[int] = None
    custom_proxy: Optional[str] = None
    cf_worker_url: Optional[str] = None
    default_language: Optional[str] = None
    sync_commands_automatically: Optional[bool] = None
    enable_user_database: Optional[bool] = None
    tracked_user_fields: Optional[List[str]] = None
    is_active: Optional[bool] = None

    model_config = ConfigDict(extra="forbid")

class BotResponse(BaseModel):
    id: int
    name: str
    username: str
    telegram_bot_id: int
    is_active: bool
    settings: Dict[str, Any]
    created_at: str

# Flow & Canvas Nodes
class FlowSaveRequest(BaseModel):
    name: Optional[str] = "Main Flow"
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    viewport: Optional[Dict[str, Any]] = {"x": 0, "y": 0, "zoom": 1}

class FlowResponse(BaseModel):
    id: int
    bot_id: int
    name: str
    is_active: bool
    version: int
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    viewport: Dict[str, Any]
    updated_at: str

# Simulator & Mockup Interaction
class SimulatorEventRequest(BaseModel):
    bot_id: int
    event_type: str = Field(..., description="'command', 'message', or 'callback'")
    payload: str = Field(..., description="E.g. '/start', 'سلام', or 'btn_buy'")
    user_id: Optional[int] = 99999999
    username: Optional[str] = "tester"
    first_name: Optional[str] = "Tester"

class SimulatorResponse(BaseModel):
    success: bool
    messages: List[Dict[str, Any]]
    alerts: List[str] = []
    chat_actions: List[str] = []
    user_state: Dict[str, Any] = {}
    logs: List[Any] = []

# Plugins
class PluginToggleRequest(BaseModel):
    plugin_key: str
    is_active: bool
