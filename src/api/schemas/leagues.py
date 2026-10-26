"""Public and authenticated response contracts for GET /api/leagues."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class PublicLeague(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str
    display_name: str = Field(alias="displayName")
    scoring_profile: str = Field(alias="scoringProfile")
    idp_enabled: bool = Field(alias="idpEnabled")
    best_ball: bool = Field(alias="bestBall")
    roster_settings: dict[str, JsonValue] = Field(alias="rosterSettings")
    active: bool


class UserDefaultTeam(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    owner_id: str = Field(alias="ownerId")
    team_name: str = Field(alias="teamName")


class AuthenticatedLeague(PublicLeague):
    user_default_team: UserDefaultTeam | None = Field(default=None, alias="userDefaultTeam")


class PublicLeaguesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    leagues: list[PublicLeague]
    default_key: str | None = Field(alias="defaultKey")


class AuthenticatedLeaguesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    leagues: list[AuthenticatedLeague]
    default_key: str | None = Field(alias="defaultKey")
    user_default_key: str | None = Field(alias="userDefaultKey")


LeaguesResponse = PublicLeaguesResponse | AuthenticatedLeaguesResponse
