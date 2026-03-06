#!/usr/bin/env python3
"""GA4 MCP Server - versione remota HTTP."""

import base64
import json
import os
import sys
from typing import Any, Dict, List, Optional

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Filter, FilterExpression,
    Metric, OrderBy, RunRealtimeReportRequest, RunReportRequest,
)
from google.oauth2 import service_account
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

GA4_KEY_JSON = os.environ.get("GA4_KEY_JSON", "")
GA4_KEY_FILE = os.environ.get("GA4_KEY_FILE", "")
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "")
GA4_PROPERTIES_MAP = os.environ.get("GA4_PROPERTIES_MAP", "")
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
PORT = int(os.environ.get("PORT", "8000"))
TRANSPORT = os.environ.get("MCP_TRANSPORT", "streamable_http")
BASE_URL = "https://web-production-4bc4f.up.railway.app"

mcp = FastMCP("ga4_mcp", stateless_http=True)


def _parse_properties_map() -> Dict[str, str]:
    result = {}
    if GA4_PROPERTIES_MAP:
        for entry in GA4_PROPERTIES_MAP.split(","):
            entry = entry.strip()
            if "=" in entry:
                name, pid = entry.split("=", 1)
                result[name.strip()] = pid.strip()
    if GA4_PROPERTY_ID:
        result["default"] = GA4_PROPERTY_ID
    return result


PROPERTIES = _parse_properties_map()


def _get_client() -> BetaAnalyticsDataClient:
    if GA4_KEY_JSON:
        try:
            key_data = json.loads(base64.b64decode(GA4_KEY_JSON).decode("utf-8"))
        except Exception:
            key_data = json.loads(GA4_KEY_JSON)
        credentials = service_account.Credentials.from_service_account_info(key_data, scopes=SCOPES)
    elif GA4_KEY_FILE:
        if not os.path.exists(GA4_KEY_FILE):
            raise FileNotFoundError(f"File chiave non trovato: {GA4_KEY_FILE}")
        credentials = service_account.Credentials.from_service_account_file(GA4_KEY_FILE, scopes=SCOPES)
    else:
        raise ValueError("Nessuna credenziale GA4 configurata.")
    return BetaAnalyticsDataClient(credentials=credentials)


def _resolve_property(property_id: Optional[str]) -> str:
    if not property_id:
        if not GA4_PROPERTY_ID:
            raise ValueError(f"Property disponibili: {list(PROPERTIES.keys())}")
        return f"properties/{GA4_PROPERTY_ID}"
    if property_id in PROPERTIES:
        return f"properties/{PROPERTIES[property_id]}"
    return f"properties/{property_id}"


def _date_range(start: str, end: str) -> DateRange:
    return DateRange(start_date=start, end_date=end)


def _rows_to_list(response) -> List[Dict[str, Any]]:
    dim_headers = [h.name for h in response.dimension_headers]
    met_headers = [h.name for h in response.metric_headers]
    rows = []
    for row in response.rows:
        record = {}
        for i, val in enumerate(row.dimension_values):
            record[dim_headers[i]] = val.value
        for i, val in enumerate(row.metric_values):
            record[met_headers[i]] = val.value
        rows.append(record)
    return rows


def _format_rows(rows: List[Dict], fmt: str, title: str = "") -> str:
    if fmt == "json":
        return json.dumps({"title": title, "rows": rows, "count": len(rows)}, indent=2)
    if not rows:
        return f"## {title}\n\nNessun dato disponibile."
    lines = [f"## {title}", f"*{len(rows)} righe*\n"]
    headers = list(rows[0].keys())
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


PROPERTY_FIELD_DESC = f"GA4 Property ID o nome. Configurate: {list(PROPERTIES.keys()) or ['default']}."


class DateRangeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    property_id: Optional[str] = Field(None, description=PROPERTY_FIELD_DESC)
    start_date: str = Field("30daysAgo")
    end_date: str = Field("today")
    limit: int = Field(20, ge=1, le=100)
    response_format: str = Field("markdown")


class MetricsInput(DateRangeInput):
    dimensions: Optional[List[str]] = Field(None)


class PageInput(DateRangeInput):
    min_pageviews: Optional[int] = Field(None, ge=0)


class FunnelInput(DateRangeInput):
    steps: List[str] = Field(min_length=2, max_length=10)


@mcp.tool(name="ga4_list_properties")
async def ga4_list_properties() -> str:
    """Elenca le property GA4 disponibili."""
    if not PROPERTIES:
        return "Nessuna property configurata."
    lines = ["## Property GA4\n", "| Nome | ID |", "|------|-----|"]
    for name, pid in PROPERTIES.items():
        lines.append(f"| {name} | {pid} |")
    return "\n".join(lines)


@mcp.tool(name="ga4_get_overview")
async def ga4_get_overview(params: MetricsInput) -> str:
    """Overview GA4: sessioni, utenti, pageviews, bounce rate, durata sessione."""
    client = _get_client()
    dims = [Dimension(name=d) for d in (params.dimensions or [])]
    response = client.run_report(RunReportRequest(
        property=_resolve_property(params.property_id), dimensions=dims,
        metrics=[Metric(name="sessions"), Metric(name="totalUsers"), Metric(name="newUsers"),
                 Metric(name="screenPageViews"), Metric(name="bounceRate"),
                 Metric(name="averageSessionDuration")],
        date_ranges=[_date_range(params.start_date, params.end_date)], limit=params.limit,
    ))
    return _format_rows(_rows_to_list(response), params.response_format,
                        f"Overview GA4 ({params.start_date} -> {params.end_date})")


@mcp.tool(name="ga4_get_channel_report")
async def ga4_get_channel_report(params: DateRangeInput) -> str:
    """Traffico per canale GA4."""
    client = _get_client()
    response = client.run_report(RunReportRequest(
        property=_resolve_property(params.property_id),
        dimensions=[Dimension(name="sessionDefaultChannelGroup"),
                    Dimension(name="sessionSourceMedium")],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers"), Metric(name="conversions"),
                 Metric(name="bounceRate"), Metric(name="averageSessionDuration")],
        date_ranges=[_date_range(params.start_date, params.end_date)],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=params.limit,
    ))
    return _format_rows(_rows_to_list(response), params.response_format,
                        f"Canali ({params.start_date} -> {params.end_date})")


@mcp.tool(name="ga4_get_realtime")
async def ga4_get_realtime(params: DateRangeInput) -> str:
    """Utenti attivi in tempo reale GA4."""
    client = _get_client()
    prop = _resolve_property(params.property_id)
    pages = _rows_to_list(client.run_realtime_report(RunRealtimeReportRequest(
        property=prop, dimensions=[Dimension(name="unifiedScreenName")],
        metrics=[Metric(name="activeUsers")], limit=10)))
    countries = _rows_to_list(client.run_realtime_report(RunRealtimeReportRequest(
        property=prop, dimensions=[Dimension(name="countryId")],
        metrics=[Metric(name="activeUsers")], limit=10)))
    devices = _rows_to_list(client.run_realtime_report(RunRealtimeReportRequest(
        property=prop, dimensions=[Dimension(name="deviceCategory")],
        metrics=[Metric(name="activeUsers")], limit=5)))
    total = sum(int(p.get("activeUsers", 0)) for p in pages)
    if params.response_format == "json":
        return json.dumps({"active_users_total": total, "pages": pages,
                           "countries": countries, "devices": devices}, indent=2)
    return "\n\n".join([
        f"## Real-Time\n**Utenti attivi: {total}**",
        _format_rows(pages, "markdown", "Top Pagine"),
        _format_rows(countries, "markdown", "Top Paesi"),
        _format_rows(devices, "markdown", "Dispositivi"),
    ])


@mcp.tool(name="ga4_get_device_country_report")
async def ga4_get_device_country_report(params: DateRangeInput) -> str:
    """Traffico GA4 per dispositivo e paese."""
    client = _get_client()
    prop = _resolve_property(params.property_id)
    dr = [_date_range(params.start_date, params.end_date)]
    metrics = [Metric(name="sessions"), Metric(name="totalUsers"),
               Metric(name="bounceRate"), Metric(name="averageSessionDuration")]
    rows_device = _rows_to_list(client.run_report(RunReportRequest(
        property=prop, dimensions=[Dimension(name="deviceCategory")],
        metrics=metrics, date_ranges=dr,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)])))
    rows_country = _rows_to_list(client.run_report(RunReportRequest(
        property=prop, dimensions=[Dimension(name="country")],
        metrics=metrics, date_ranges=dr,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=params.limit)))
    if params.response_format == "json":
        return json.dumps({"devices": rows_device, "countries": rows_country}, indent=2)
    return "\n\n".join([
        _format_rows(rows_device, "markdown", f"Dispositivi ({params.start_date} -> {params.end_date})"),
        _format_rows(rows_country, "markdown", f"Paesi ({params.start_date} -> {params.end_date})"),
    ])


@mcp.tool(name="ga4_get_pages_report")
async def ga4_get_pages_report(params: PageInput) -> str:
    """Pagine piu visitate GA4."""
    client = _get_client()
    response = client.run_report(RunReportRequest(
        property=_resolve_property(params.property_id),
        dimensions=[Dimension(name="pagePath"), Dimension(name="pageTitle")],
        metrics=[Metric(name="screenPageViews"), Metric(name="totalUsers"),
                 Metric(name="averageSessionDuration"), Metric(name="bounceRate"),
                 Metric(name="engagementRate")],
        date_ranges=[_date_range(params.start_date, params.end_date)],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
        limit=params.limit,
    ))
    return _format_rows(_rows_to_list(response), params.response_format,
                        f"Top Pagine ({params.start_date} -> {params.end_date})")


@mcp.tool(name="ga4_get_conversions")
async def ga4_get_conversions(params: DateRangeInput) -> str:
    """Conversioni GA4 per canale e evento."""
    client = _get_client()
    prop = _resolve_property(params.property_id)
    dr = [_date_range(params.start_date, params.end_date)]
    rows_channel = _rows_to_list(client.run_report(RunReportRequest(
        property=prop, dimensions=[Dimension(name="sessionDefaultChannelGroup")],
        metrics=[Metric(name="conversions"), Metric(name="sessions"), Metric(name="totalUsers")],
        date_ranges=dr,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="conversions"), desc=True)],
        limit=params.limit)))
    rows_events = _rows_to_list(client.run_report(RunReportRequest(
        property=prop, dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="conversions"), Metric(name="eventCount")],
        date_ranges=dr,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="conversions"), desc=True)],
        limit=params.limit)))
    if params.response_format == "json":
        return json.dumps({"by_channel": rows_channel, "by_event": rows_events}, indent=2)
    return "\n\n".join([
        _format_rows(rows_channel, "markdown",
                     f"Conversioni per Canale ({params.start_date} -> {params.end_date})"),
        _format_rows(rows_events, "markdown", "Conversioni per Evento"),
    ])


@mcp.tool(name="ga4_get_funnel")
async def ga4_get_funnel(params: FunnelInput) -> str:
    """Analisi funnel GA4 con drop-off tra step."""
    client = _get_client()
    prop = _resolve_property(params.property_id)
    dr = [_date_range(params.start_date, params.end_date)]
    step_data = []
    for step_path in params.steps:
        response = client.run_report(RunReportRequest(
            property=prop, dimensions=[Dimension(name="pagePath")],
            metrics=[Metric(name="totalUsers"), Metric(name="screenPageViews")],
            date_ranges=dr,
            dimension_filter=FilterExpression(filter=Filter(
                field_name="pagePath",
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.BEGINS_WITH, value=step_path)))))
        users = sum(int(r.metric_values[0].value) for r in response.rows) if response.rows else 0
        step_data.append({"step": step_path, "users": users})
    for i, step in enumerate(step_data):
        if i == 0:
            step["drop_off_pct"] = "-"
            step["conversion_from_prev"] = "-"
        else:
            prev, curr = step_data[i - 1]["users"], step["users"]
            drop = round((1 - curr / prev) * 100, 1) if prev > 0 else 0.0
            conv = round(curr / prev * 100, 1) if prev > 0 else 0.0
            step["drop_off_pct"] = f"{drop}%"
            step["conversion_from_prev"] = f"{conv}%"
    if params.response_format == "json":
        return json.dumps({"funnel": step_data}, indent=2)
    lines = [f"## Funnel ({params.start_date} -> {params.end_date})\n"]
    lines.append("| Step | Pagina | Utenti | Conv. | Drop-off |")
    lines.append("|------|--------|--------|-------|----------|")
    for i, step in enumerate(step_data):
        lines.append(
            f"| {i + 1} | {step['step']} | {step['users']:,} | "
            f"{step['conversion_from_prev']} | {step['drop_off_pct']} |")
    if step_data[0]["users"] > 0:
        overall = round(step_data[-1]["users"] / step_data[0]["users"] * 100, 2)
        lines.append(f"\n**Completamento funnel: {overall}%**")
    return "\n".join(lines)


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import JSONResponse, RedirectResponse, Response

    if TRANSPORT == "stdio":
        mcp.run()
    else:
        print(f"GA4 MCP Server su porta {PORT}", file=sys.stderr)
        print(f"Property: {list(PROPERTIES.keys())}", file=sys.stderr)

        app = FastAPI(redirect_slashes=False)
        mcp_app = mcp.streamable_http_app()
        app.mount("/mcp/", mcp_app)
        app.mount("/mcp", mcp_app)


        @app.get("/.well-known/oauth-protected-resource")
        @app.get("/.well-known/oauth-protected-resource/mcp")
        async def oauth_protected_resource(request: Request):
            return JSONResponse({
                "resource": f"{BASE_URL}/mcp",
                "authorization_servers": [],
                "bearer_methods_supported": [],
                "scopes_supported": [],
            })

        @app.get("/.well-known/oauth-authorization-server")
        async def oauth_authorization_server(request: Request):
            return JSONResponse({
                "issuer": BASE_URL,
                "authorization_endpoint": f"{BASE_URL}/oauth/authorize",
                "token_endpoint": f"{BASE_URL}/oauth/token",
                "registration_endpoint": f"{BASE_URL}/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256"],
            })

        @app.post("/register")
        async def dynamic_client_registration(request: Request):
            body_json = await request.json()
            return JSONResponse({
                "client_id": "claude-mcp-client",
                "client_secret": "not-used",
                "redirect_uris": body_json.get("redirect_uris", []),
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "client_name": body_json.get("client_name", "Claude"),
            })

        @app.get("/oauth/authorize")
        async def oauth_authorize(request: Request):
            p = dict(request.query_params)
            redirect_uri = p.get("redirect_uri", "")
            state = p.get("state", "")
            return RedirectResponse(f"{redirect_uri}?code=ga4-mcp-code&state={state}")

        @app.post("/oauth/token")
        async def oauth_token(request: Request):
            return JSONResponse({
                "access_token": "ga4-mcp-token",
                "token_type": "Bearer",
                "expires_in": 86400,
            })

        @app.get("/")
        async def root():
            return {"status": "ok", "server": "ga4_mcp"}

        uvicorn.run(app, host="0.0.0.0", port=PORT)
