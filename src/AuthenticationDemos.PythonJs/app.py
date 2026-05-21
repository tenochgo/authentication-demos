import json
import os
import secrets
import struct
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import jwt
import msal
import pyodbc
from azure.core.credentials import AccessToken, TokenCredential
from azure.identity import ClientSecretCredential
from azure.storage.blob import BlobServiceClient
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "appsettings.json"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

_state_lock = Lock()
_state: dict[str, dict[str, Any]] = {}


class StaticTokenCredential(TokenCredential):
    def __init__(self, token: str):
        self._token = token

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken(token=self._token, expires_on=int(time.time()) + 3600)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy appsettings.json.template to appsettings.json and fill values."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


config = load_config()
azure_ad = config["AzureAd"]
azure_resources = config["AzureResources"]
downstream_apis = config.get("DownstreamApis", {})


@app.context_processor
def inject_user_context() -> dict[str, Any]:
    user = get_session_state().get("user")
    return {"signed_in": bool(user), "user_name": user.get("name") if user else None}


def get_session_state() -> dict[str, Any]:
    sid = session.get("sid")
    if not sid:
        sid = str(uuid.uuid4())
        session["sid"] = sid
    with _state_lock:
        if sid not in _state:
            _state[sid] = {
                "logs": {"service_principal": [], "obo": []},
                "allowed_tables": {"service_principal": [], "obo": []},
            }
        return _state[sid]


def append_log(mode: str, level: str, message: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    state = get_session_state()
    state["logs"][mode].append(entry)


def clear_logs(mode: str) -> None:
    state = get_session_state()
    state["logs"][mode] = []


def log_token_claims(mode: str, token: str, label: str) -> None:
    try:
        claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        append_log(mode, "token", f"{label} — Token acquired successfully")
        append_log(mode, "token", f"  Issuer: {claims.get('iss', '<unknown>')}")
        aud = claims.get("aud")
        append_log(mode, "token", f"  Audience: {aud if isinstance(aud, str) else ', '.join(aud or [])}")
        exp = claims.get("exp")
        nbf = claims.get("nbf")
        if exp:
            append_log(mode, "token", f"  Expires: {datetime.fromtimestamp(exp, timezone.utc).isoformat()}")
        if nbf:
            append_log(mode, "token", f"  Not Before: {datetime.fromtimestamp(nbf, timezone.utc).isoformat()}")
        for key, value in claims.items():
            append_log(mode, "claim", f"  {key}: {value}")
    except Exception as ex:  # noqa: BLE001
        append_log(mode, "warning", f"{label}: Could not decode token — {ex}")


def create_service_principal_credential() -> ClientSecretCredential:
    return ClientSecretCredential(
        tenant_id=azure_ad["TenantId"],
        client_id=azure_ad["ClientId"],
        client_secret=azure_ad["ClientSecret"],
    )


def get_msal_app() -> msal.ConfidentialClientApplication:
    authority = f"{azure_ad['Instance'].rstrip('/')}/{azure_ad['TenantId']}"
    return msal.ConfidentialClientApplication(
        client_id=azure_ad["ClientId"],
        authority=authority,
        client_credential=azure_ad["ClientSecret"],
    )


def get_storage_client_for_mode(mode: str) -> BlobServiceClient:
    account_url = f"https://{azure_resources['StorageAccountName']}.blob.core.windows.net"
    if mode == "service_principal":
        credential = create_service_principal_credential()
    else:
        token = acquire_obo_token("storage")
        credential = StaticTokenCredential(token)
    return BlobServiceClient(account_url=account_url, credential=credential)


def _escape_identifier(identifier: str) -> str:
    return f"[{identifier.replace(']', ']]')}]"


def _sql_connect(access_token: str) -> pyodbc.Connection:
    token_bytes = access_token.encode("utf-16-le")
    token_struct = struct.pack("=i", len(token_bytes)) + token_bytes
    conn_str = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{azure_resources['SqlServer']},1433;"
        f"Database={azure_resources['SqlDatabase']};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str, attrs_before={1256: token_struct})


def get_sql_token_for_mode(mode: str) -> str:
    if mode == "service_principal":
        return create_service_principal_credential().get_token("https://database.windows.net/.default").token
    return acquire_obo_token("sql")


def get_allowed_tables(mode: str) -> list[dict[str, str]]:
    token = get_sql_token_for_mode(mode)
    tables: list[dict[str, str]] = []
    with _sql_connect(token) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT TABLE_SCHEMA, TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_SCHEMA, TABLE_NAME
            """
        )
        for row in cursor.fetchall():
            tables.append({"schema": row[0], "tableName": row[1], "fullName": f"{row[0]}.{row[1]}"})
    state = get_session_state()
    state["allowed_tables"][mode] = tables
    return tables


def run_select_query(mode: str, schema: str, table: str, top_n: int) -> dict[str, Any]:
    top_n = max(1, min(int(top_n), 100))
    state = get_session_state()
    allowed = state["allowed_tables"][mode]
    matched = next((t for t in allowed if t["schema"] == schema and t["tableName"] == table), None)
    if not matched:
        append_log(mode, "error", f"Table '{schema}.{table}' is not in the allowed list. Aborting query.")
        return {"columns": [], "rows": []}

    token = get_sql_token_for_mode(mode)
    safe_schema = _escape_identifier(matched["schema"])
    safe_table = _escape_identifier(matched["tableName"])
    sql = f"SELECT * FROM {safe_schema}.{safe_table} ORDER BY (SELECT NULL) OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"

    with _sql_connect(token) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, top_n)
        columns = [col[0] for col in cursor.description]
        rows = []
        for db_row in cursor.fetchall():
            row = {column: value for column, value in zip(columns, db_row)}
            rows.append(row)

    append_log(mode, "info", f"Query returned {len(rows)} row(s) with {len(columns)} column(s)")
    return {"columns": columns, "rows": rows}


def require_user() -> dict[str, Any] | None:
    state = get_session_state()
    return state.get("user")


def acquire_obo_token(target: str) -> str:
    state = get_session_state()
    user_token = state.get("user_access_token")
    if not user_token:
        raise RuntimeError("User is not signed in.")

    scopes = (
        downstream_apis.get("Storage", {}).get("Scopes", ["https://storage.azure.com/user_impersonation"])
        if target == "storage"
        else downstream_apis.get("Sql", {}).get("Scopes", ["https://database.windows.net/user_impersonation"])
    )

    result = get_msal_app().acquire_token_on_behalf_of(user_assertion=user_token, scopes=scopes)
    if "access_token" not in result:
        msg = result.get("error_description") or result.get("error") or "Unknown OBO failure"
        raise RuntimeError(msg)
    return result["access_token"]


def error_response(mode: str, message: str, status: int = 500, log_details: str | None = None) -> Any:
    append_log(mode, "error", log_details or message)
    return jsonify({"ok": False, "error": message}), status


@app.get("/")
def home() -> str:
    return render_template("home.html")


@app.get("/service-principal")
def service_principal_page() -> str:
    return render_template("service_principal.html")


@app.get("/on-behalf-of")
def on_behalf_of_page() -> str:
    user = require_user()
    return render_template("on_behalf_of.html", user=user)


@app.get("/MicrosoftIdentity/Account/SignIn")
def signin() -> Any:
    redirect_uri = url_for("signin_callback", _external=True)
    app_scope = f"api://{azure_ad['ClientId']}/access_as_user"
    flow = get_msal_app().initiate_auth_code_flow(
        scopes=[app_scope, "openid", "profile", "offline_access"],
        redirect_uri=redirect_uri,
    )
    state = get_session_state()
    state["auth_flow"] = flow
    return redirect(flow["auth_uri"])


@app.get(azure_ad.get("CallbackPath", "/signin-oidc"))
def signin_callback() -> Any:
    state = get_session_state()
    flow = state.get("auth_flow")
    if not flow:
        return "Missing auth flow state.", 400

    result = get_msal_app().acquire_token_by_auth_code_flow(flow, request.args)
    if "access_token" not in result:
        err = result.get("error_description") or result.get("error") or "Unknown sign-in error"
        return f"Sign-in failed: {err}", 401

    claims = result.get("id_token_claims", {})
    state["user"] = {
        "name": claims.get("name") or claims.get("preferred_username") or "Unknown User",
        "claims": claims,
    }
    state["user_access_token"] = result["access_token"]
    return redirect(url_for("on_behalf_of_page"))


@app.get("/MicrosoftIdentity/Account/SignOut")
def signout() -> Any:
    state = get_session_state()
    state.pop("user", None)
    state.pop("user_access_token", None)
    return redirect(azure_ad.get("SignedOutCallbackPath", "/signout-callback-oidc"))


@app.get(azure_ad.get("SignedOutCallbackPath", "/signout-callback-oidc"))
def signout_callback() -> Any:
    return redirect(url_for("home"))


@app.post("/api/service-principal/run")
def run_service_principal() -> Any:
    mode = "service_principal"
    clear_logs(mode)

    try:
        append_log(mode, "info", "=== Service Principal Demo Started ===")
        append_log(mode, "info", f"Tenant ID: {azure_ad['TenantId']}")
        append_log(mode, "info", f"Client ID: {azure_ad['ClientId']}")
        secret_tail = azure_ad.get("ClientSecret", "")[-4:]
        append_log(mode, "info", f"Client Secret: ****{secret_tail}")

        credential = create_service_principal_credential()

        append_log(mode, "info", "")
        append_log(mode, "info", "--- Azure Storage ---")
        append_log(mode, "info", f"Storage Account: {azure_resources['StorageAccountName']}")
        append_log(mode, "info", "Acquiring token for https://storage.azure.com/.default ...")
        storage_token = credential.get_token("https://storage.azure.com/.default").token
        log_token_claims(mode, storage_token, "Storage Token")

        append_log(mode, "info", "")
        append_log(mode, "info", "--- Azure SQL Database ---")
        append_log(mode, "info", f"SQL Server: {azure_resources['SqlServer']}")
        append_log(mode, "info", f"Database: {azure_resources['SqlDatabase']}")
        append_log(mode, "info", "Acquiring token for https://database.windows.net/.default ...")
        sql_token = credential.get_token("https://database.windows.net/.default").token
        log_token_claims(mode, sql_token, "SQL Token")

        append_log(mode, "info", "")
        append_log(mode, "info", "=== Service Principal Demo Complete ===")
        return jsonify({"ok": True})
    except Exception as ex:  # noqa: BLE001
        return error_response(mode, "Unexpected error while running service principal demo.", 500, f"Unexpected error: {ex}")


@app.post("/api/on-behalf-of/run")
def run_obo() -> Any:
    mode = "obo"
    clear_logs(mode)
    if not require_user():
        return jsonify({"ok": False, "error": "Not signed in"}), 401

    try:
        append_log(mode, "info", "=== On Behalf Of Demo Started ===")
        append_log(mode, "info", "User signed in via OpenID Connect")

        claims = get_session_state().get("user", {}).get("claims", {})
        append_log(mode, "token", "--- ID Token Claims ---")
        for k, v in claims.items():
            append_log(mode, "claim", f"  {k}: {v}")

        storage_scopes = downstream_apis.get("Storage", {}).get("Scopes", ["https://storage.azure.com/user_impersonation"])
        append_log(mode, "info", "")
        append_log(mode, "info", "--- Azure Storage (On Behalf Of) ---")
        append_log(mode, "info", f"Requesting OBO token for scopes: {', '.join(storage_scopes)}")
        storage_token = acquire_obo_token("storage")
        log_token_claims(mode, storage_token, "Storage OBO Token")

        sql_scopes = downstream_apis.get("Sql", {}).get("Scopes", ["https://database.windows.net/user_impersonation"])
        append_log(mode, "info", "")
        append_log(mode, "info", "--- Azure SQL Database (On Behalf Of) ---")
        append_log(mode, "info", f"Requesting OBO token for scopes: {', '.join(sql_scopes)}")
        sql_token = acquire_obo_token("sql")
        log_token_claims(mode, sql_token, "SQL OBO Token")

        append_log(mode, "info", "")
        append_log(mode, "info", "=== On Behalf Of Demo Complete ===")
        return jsonify({"ok": True})
    except Exception as ex:  # noqa: BLE001
        message = str(ex)
        if "interaction_required" in message or "consent" in message.lower():
            append_log(mode, "warning", "User interaction required for delegated access.")
            return jsonify({"ok": False, "error": "User interaction required for delegated access."}), 403
        return error_response(mode, "Unexpected error while running OBO demo.", 500, f"Unexpected error: {message}")


@app.get("/api/logs")
def get_logs() -> Any:
    mode = request.args.get("mode", "service_principal")
    if mode not in {"service_principal", "obo"}:
        return jsonify({"error": "Invalid mode"}), 400
    return jsonify(get_session_state()["logs"][mode])


@app.delete("/api/logs")
def delete_logs() -> Any:
    mode = request.args.get("mode", "service_principal")
    if mode not in {"service_principal", "obo"}:
        return jsonify({"error": "Invalid mode"}), 400
    clear_logs(mode)
    return jsonify({"ok": True})


@app.get("/api/<mode>/storage/containers")
def list_containers(mode: str) -> Any:
    if mode not in {"service_principal", "obo"}:
        return jsonify({"error": "Invalid mode"}), 400
    if mode == "obo" and not require_user():
        return jsonify({"error": "Not signed in"}), 401

    try:
        client = get_storage_client_for_mode(mode)
        append_log(mode, "info", f"Listing containers in storage account: {azure_resources['StorageAccountName']}")
        containers = [container.name for container in client.list_containers()]
        append_log(mode, "info", f"Found {len(containers)} container(s): {', '.join(containers)}")
        return jsonify(containers)
    except Exception as ex:  # noqa: BLE001
        return error_response(mode, "Error listing containers.", 500, f"Error listing containers: {ex}")


@app.get("/api/<mode>/storage/blobs")
def list_blobs(mode: str) -> Any:
    if mode not in {"service_principal", "obo"}:
        return jsonify({"error": "Invalid mode"}), 400
    if mode == "obo" and not require_user():
        return jsonify({"error": "Not signed in"}), 401

    container = request.args.get("container")
    prefix = request.args.get("prefix")
    if not container:
        return jsonify({"error": "Missing container"}), 400

    try:
        client = get_storage_client_for_mode(mode).get_container_client(container)
        append_log(mode, "info", f"Listing blobs in container '{container}'" + (f" with prefix '{prefix}'" if prefix else ""))
        items: list[dict[str, Any]] = []
        for item in client.walk_blobs(name_starts_with=prefix, delimiter="/"):
            if hasattr(item, "prefix"):
                items.append({"name": item.prefix, "isFolder": True, "size": None, "lastModified": None})
            else:
                props = item
                items.append(
                    {
                        "name": props.name,
                        "isFolder": False,
                        "size": props.size,
                        "lastModified": props.last_modified.isoformat() if props.last_modified else None,
                    }
                )

        append_log(mode, "info", f"Found {len(items)} item(s)" + (f" under '{prefix}'" if prefix else " at root"))
        return jsonify(items)
    except Exception as ex:  # noqa: BLE001
        return error_response(mode, "Error listing blobs.", 500, f"Error listing blobs: {ex}")


@app.get("/api/<mode>/sql/tables")
def list_tables(mode: str) -> Any:
    if mode not in {"service_principal", "obo"}:
        return jsonify({"error": "Invalid mode"}), 400
    if mode == "obo" and not require_user():
        return jsonify({"error": "Not signed in"}), 401

    try:
        append_log(mode, "info", "Querying INFORMATION_SCHEMA.TABLES to discover tables...")
        tables = get_allowed_tables(mode)
        append_log(mode, "info", f"Found {len(tables)} table(s): {', '.join(t['fullName'] for t in tables)}")
        return jsonify(tables)
    except Exception as ex:  # noqa: BLE001
        return error_response(mode, "Error listing tables.", 500, f"Error listing tables: {ex}")


@app.post("/api/<mode>/sql/query")
def query_table(mode: str) -> Any:
    if mode not in {"service_principal", "obo"}:
        return jsonify({"error": "Invalid mode"}), 400
    if mode == "obo" and not require_user():
        return jsonify({"error": "Not signed in"}), 401

    payload = request.get_json(silent=True) or {}
    schema = payload.get("schema")
    table = payload.get("tableName")
    top_n = payload.get("topN", 10)

    if not schema or not table:
        return jsonify({"error": "schema and tableName are required"}), 400

    try:
        append_log(mode, "info", f"Executing: SELECT * FROM [{schema}].[{table}] ORDER BY (SELECT NULL) OFFSET 0 ROWS FETCH NEXT {max(1, min(int(top_n), 100))} ROWS ONLY")
        result = run_select_query(mode, schema, table, int(top_n))
        return jsonify(result)
    except Exception as ex:  # noqa: BLE001
        return error_response(mode, "Error executing query.", 500, f"Error executing query: {ex}")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
