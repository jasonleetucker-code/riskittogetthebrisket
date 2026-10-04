// Generated from GET /api/leagues OpenAPI by scripts/generate_leagues_contract.py.
// Do not edit; run python -m scripts.generate_leagues_contract.
export const LEAGUES_SCHEMA_SHA256 = "0db4f2c0171335dbcb12bdc6bfe99c387809ee79f872bb9fc699f2770e26d1e1";

/**
 * @typedef {Object} PublicLeague
 * @property {string} key
 * @property {string} displayName
 * @property {string} scoringProfile
 * @property {boolean} idpEnabled
 * @property {boolean} bestBall
 * @property {Record<string, unknown>} rosterSettings
 * @property {boolean} active
 */

/**
 * @typedef {Object} AuthenticatedLeague
 * @property {string} key
 * @property {string} displayName
 * @property {string} scoringProfile
 * @property {boolean} idpEnabled
 * @property {boolean} bestBall
 * @property {Record<string, unknown>} rosterSettings
 * @property {boolean} active
 * @property {UserDefaultTeam|null} [userDefaultTeam]
 */

/**
 * @typedef {Object} UserDefaultTeam
 * @property {string} ownerId
 * @property {string} teamName
 */

/**
 * @typedef {Object} PublicLeaguesResponse
 * @property {Array<PublicLeague>} leagues
 * @property {string|null} defaultKey
 */

/**
 * @typedef {Object} AuthenticatedLeaguesResponse
 * @property {Array<AuthenticatedLeague>} leagues
 * @property {string|null} defaultKey
 * @property {string|null} userDefaultKey
 */

/** @typedef {PublicLeaguesResponse|AuthenticatedLeaguesResponse} LeaguesResponse */

const MODELS = {
  "AuthenticatedLeague": {
    "fields": {
      "active": "boolean",
      "bestBall": "boolean",
      "displayName": "string",
      "idpEnabled": "boolean",
      "key": "string",
      "rosterSettings": "object",
      "scoringProfile": "string",
      "userDefaultTeam": "model:UserDefaultTeam|null"
    },
    "required": [
      "active",
      "bestBall",
      "displayName",
      "idpEnabled",
      "key",
      "rosterSettings",
      "scoringProfile"
    ]
  },
  "AuthenticatedLeaguesResponse": {
    "fields": {
      "defaultKey": "string|null",
      "leagues": "array:model:AuthenticatedLeague",
      "userDefaultKey": "string|null"
    },
    "required": [
      "defaultKey",
      "leagues",
      "userDefaultKey"
    ]
  },
  "PublicLeague": {
    "fields": {
      "active": "boolean",
      "bestBall": "boolean",
      "displayName": "string",
      "idpEnabled": "boolean",
      "key": "string",
      "rosterSettings": "object",
      "scoringProfile": "string"
    },
    "required": [
      "active",
      "bestBall",
      "displayName",
      "idpEnabled",
      "key",
      "rosterSettings",
      "scoringProfile"
    ]
  },
  "PublicLeaguesResponse": {
    "fields": {
      "defaultKey": "string|null",
      "leagues": "array:model:PublicLeague"
    },
    "required": [
      "defaultKey",
      "leagues"
    ]
  },
  "UserDefaultTeam": {
    "fields": {
      "ownerId": "string",
      "teamName": "string"
    },
    "required": [
      "ownerId",
      "teamName"
    ]
  }
};

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function matchesKind(value, kind) {
  if (kind.includes("|")) return kind.split("|").some((part) => matchesKind(value, part));
  if (kind === "null") return value === null;
  if (kind === "object") return isRecord(value);
  if (kind === "integer") return Number.isInteger(value);
  if (kind === "number") return typeof value === "number" && Number.isFinite(value);
  if (kind.startsWith("model:")) return matchesModel(value, kind.slice(6));
  if (kind.startsWith("array:")) {
    return Array.isArray(value) && value.every((item) => matchesKind(item, kind.slice(6)));
  }
  return typeof value === kind;
}

function matchesModel(value, name) {
  if (!isRecord(value)) return false;
  const model = MODELS[name];
  if (!model) return false;
  return model.required.every((field) => Object.hasOwn(value, field)) &&
    Object.entries(value).every(([field, item]) =>
      Object.hasOwn(model.fields, field) && matchesKind(item, model.fields[field]));
}

/** @param {unknown} value @returns {LeaguesResponse} */
export function parseLeaguesResponse(value) {
  const model = isRecord(value) && Object.hasOwn(value, "userDefaultKey")
    ? "AuthenticatedLeaguesResponse" : "PublicLeaguesResponse";
  if (!matchesModel(value, model)) throw new Error("invalid_leagues_contract");
  return /** @type {LeaguesResponse} */ (value);
}
