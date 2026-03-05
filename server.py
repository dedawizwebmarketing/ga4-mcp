#!/usr/bin/env python3
"""
GA4 MCP Server — versione remota (HTTP) con supporto multi-property.
Deployabile su Railway, Render, o qualsiasi cloud.
"""

import base64
import json
import os
import sys
from typing import Any, Dict, List, Optional

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    OrderBy,
    RunRealtimeReportRequest,
    RunReportRequest,
)
from google.oauth2 import service_account
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# ─── Config ───────────────────────────────────────────────────────────────────

# Credenziali: stringa JSON base64 (per deploy cloud) o percorso file (per locale)
GA4_KEY_JSON   = os.environ.get("GA4_KEY_JSON", "")    # JSON base64-encoded (Railway)
GA4_KEY_FILE   = os.environ.get("GA4_KEY_FILE", "")    # percorso file (locale)
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "") # property default

# Mappa di property: "nome=id,nome2=id2"  es. "sito_a=123456,sito_b=789012"
GA4_PROPERTIES_MAP = os.environ.get("GA4_PROPERTIES_MAP", "")

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
PORT   = int(os.environ.get("PORT", "8000"))
TRANSPORT = os.environ.get("MCP_TRANSPORT", "streamable_http")  # o "stdio" per locale

mcp = FastMCP("ga4_mcp", stateless_http=True)

# ─── Properties Map ───────────────────────────────────────────────────────────

def _parse_properties_map() -> Dict[str, str]:
    """Parsa GA4_PROPERTIES_MAP in un dict {nome: property_id}."""
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

# ─── GA4 Client ───────────────────────────────────────────────────────────────

def _get_client() -> BetaAnalyticsDataClient:
    """Crea client GA4 da JSON base64 (cloud) o file (locale)."""
    if GA4_KEY_JSON:
        # Modalità cloud: credenziali come stringa base64
        try:
            key_data = json.loads(base64.b64decode(GA4_KEY_JSON).decode("utf-8"))
        except Exception:
            key_data = json.loads(GA4_KEY_JSON)
        credentials = service_account.Credentials.from_service_account_info(
            key_data, scopes=SCOPES
        )
    elif GA4_KEY_FILE:
        if not os.path.exists(GA4_KEY_FILE):
            raise FileNotFoundError(f"File chiave non trovato: {GA4_KEY_FILE}")
        credentials = service_account.Credentials.from_service_account_file(
            GA4_KEY_FILE, scopes=SCOPES
        )
    else:
        raise ValueError(
            "Nessuna credenziale GA4 configurata. "
            "Imposta GA4_KEY_JSON (cloud) o GA4_KEY_FILE (locale)."
        )
    return BetaAnalyticsDataClient(credentials=credentials)


def _resolve_property(property_id: Optional[str]) -> str:
    """Risolve property_id: può essere un ID numerico o un nome dalla mappa."""
    if not property_id:
        pid = GA4_PROPERTY_ID
        if not pid:
            available = list(PROPERTIES.keys())
            raise ValueError(
                f"Nessuna property specificata. "
                f"Property disponibili: {available}. "
                f"Passa property_id='nome' o property_id='123456789'."
            )
        return f"properties/{pid}"

    # Cerca nella mappa per nome
    if property_id in PROPERTIES:
        return f"properties/{PROPERTIES[property_id]}"

    # Assume sia un ID numerico diretto
    return f"properties/{property_id}"

# ─── Helpers ──────────────────────────────────────────────────────────────────

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
        return f"## {title}\n\nNessun dato disponibile per il periodo selezionato."
    lines = [f"## {title}", f"*{len(rows)} righe*\n"]
    headers = list(rows[0].keys())
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)

# ─── Input Models ─────────────────────────────────────────────────────────────

PROPERTY_FIELD_DESC = (
    "GA4 Property ID numerico (es. '123456789') "
    "o nome dalla mappa (es. 'sito_a'). "
    f"Property configurate: {list(PROPERTIES.keys()) or ['default']}. "
    "Se omesso usa la property di default."
)

class DateRangeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    property_id: Optional[str] = Field(None, description=PROPERTY_FIELD_DESC)
    start_date: str = Field("30daysAgo", description="Data inizio. Es: '2024-01-01', '7daysAgo', '30daysAgo', 'yesterday'")
    end_date: str = Field("today", description="Data fine. Es: '2024-12-31', 'today', 'yesterday'")
    limit: int = Field(20, description="Numero massimo di righe (1-100)", ge=1, le=100)
    response_format: str = Field("markdown", description="Formato risposta: 'markdown' o 'json'")


class MetricsInput(DateRangeInput):
    dimensions: Optional[List[str]] = Field(None, description="Dimensioni aggiuntive (es. ['date', 'country'])")


class PageInput(DateRangeInput):
    min_pageviews: Optional[int] = Field(None, description="Filtra pagine con almeno N pageviews", ge=0)


class FunnelInput(DateRangeInput):
    steps: List[str] = Field(
        description="Lista di pagePaths del funnel (es. ['/home', '/prodotto', '/checkout', '/grazie'])",
        min_length=2, max_length=10,
    )

# ─── Tool: Lista property disponibili ─────────────────────────────────────────

@mcp.tool(
    name="ga4_list_properties",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def ga4_list_properties() -> str:
    """Elenca tutte le property GA4 configurate e disponibili su questo server.

    Returns:
        str: Lista delle property con nome e ID.
    """
    if not PROPERTIES:
        return "⚠️ Nessuna property GA4 configurata. Imposta GA4_PROPERTY_ID o GA4_PROPERTIES_MAP."
    lines = ["## Property GA4 disponibili\n"]
    lines.append("| Nome | Property ID |")
    lines.append("|------|-------------|")
    for name, pid in PROPERTIES.items():
        lines.append(f"| `{name}` | `{pid}` |")
    lines.append(f"\n*Usa il nome o l'ID numerico nel campo `property_id` di ogni tool.*")
    return "\n".join(lines)

# ─── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="ga4_get_overview",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ga4_get_overview(params: MetricsInput) -> str:
    """Ottieni un report generale delle metriche GA4: sessioni, utenti, pageviews, durata media sessione, bounce rate, nuovi utenti.
    Supporta più property tramite property_id. Supporta dimensioni personalizzate.

    Args:
        params: MetricsInput con property_id, start_date, end_date, limit, response_format, dimensions opzionali.

    Returns:
        str: Tabella markdown o JSON con le metriche principali.
    """
    client = _get_client()
    dims = [Dimension(name=d) for d in (params.dimensions or [])]
    request = RunReportRequest(
        property=_resolve_property(params.property_id),
        dimensions=dims,
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="screenPageViews"),
            Metric(name="bounceRate"),
            Metric(name="averageSessionDuration"),
        ],
        date_ranges=[_date_range(params.start_date, params.end_date)],
        limit=params.limit,
    )
    response = client.run_report(request)
    rows = _rows_to_list(response)
    prop_label = params.property_id or "default"
    return _format_rows(rows, params.response_format, f"Overview GA4 — {prop_label} ({params.start_date} → {params.end_date})")


@mcp.tool(
    name="ga4_get_channel_report",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ga4_get_channel_report(params: DateRangeInput) -> str:
    """Analisi del traffico per canale/source/medium GA4.
    Mostra sessioni, utenti, conversioni e bounce rate per ogni canale. Supporta più property.

    Args:
        params: DateRangeInput con property_id, start_date, end_date, limit, response_format.

    Returns:
        str: Tabella con breakdown per defaultChannelGroup e sessionSourceMedium.
    """
    client = _get_client()
    request = RunReportRequest(
        property=_resolve_property(params.property_id),
        dimensions=[
            Dimension(name="sessionDefaultChannelGroup"),
            Dimension(name="sessionSourceMedium"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
            Metric(name="bounceRate"),
            Metric(name="averageSessionDuration"),
        ],
        date_ranges=[_date_range(params.start_date, params.end_date)],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=params.limit,
    )
    response = client.run_report(request)
    rows = _rows_to_list(response)
    prop_label = params.property_id or "default"
    return _format_rows(rows, params.response_format, f"Canali — {prop_label} ({params.start_date} → {params.end_date})")


@mcp.tool(
    name="ga4_get_realtime",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def ga4_get_realtime(params: DateRangeInput) -> str:
    """Dati in tempo reale GA4: utenti attivi ora, pagine più viste, paesi e dispositivi live. Supporta più property.

    Args:
        params: DateRangeInput (start_date/end_date ignorati per real-time).

    Returns:
        str: Report real-time con utenti attivi, top pages, top countries, top devices.
    """
    client = _get_client()
    prop = _resolve_property(params.property_id)

    req_pages = RunRealtimeReportRequest(
        property=prop,
        dimensions=[Dimension(name="unifiedScreenName")],
        metrics=[Metric(name="activeUsers")],
        limit=10,
    )
    req_countries = RunRealtimeReportRequest(
        property=prop,
        dimensions=[Dimension(name="countryId")],
        metrics=[Metric(name="activeUsers")],
        limit=10,
    )
    req_devices = RunRealtimeReportRequest(
        property=prop,
        dimensions=[Dimension(name="deviceCategory")],
        metrics=[Metric(name="activeUsers")],
        limit=5,
    )

    pages    = _rows_to_list(client.run_realtime_report(req_pages))
    countries = _rows_to_list(client.run_realtime_report(req_countries))
    devices  = _rows_to_list(client.run_realtime_report(req_devices))
    total    = sum(int(p.get("activeUsers", 0)) for p in pages)
    prop_label = params.property_id or "default"

    if params.response_format == "json":
        return json.dumps({"property": prop_label, "active_users_total": total,
                           "top_pages": pages, "top_countries": countries, "top_devices": devices}, indent=2)

    return "\n\n".join([
        f"## 🟢 Real-Time — {prop_label}\n**Utenti attivi ora: {total}**",
        _format_rows(pages, "markdown", "Top Pagine"),
        _format_rows(countries, "markdown", "Top Paesi"),
        _format_rows(devices, "markdown", "Dispositivi"),
    ])


@mcp.tool(
    name="ga4_get_device_country_report",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ga4_get_device_country_report(params: DateRangeInput) -> str:
    """Analisi GA4 per dispositivo (desktop, mobile, tablet) e per paese. Supporta più property.

    Args:
        params: DateRangeInput con property_id, start_date, end_date, limit, response_format.

    Returns:
        str: Due tabelle — breakdown per dispositivo e per paese.
    """
    client = _get_client()
    prop = _resolve_property(params.property_id)
    dr = [_date_range(params.start_date, params.end_date)]
    shared_metrics = [
        Metric(name="sessions"), Metric(name="totalUsers"),
        Metric(name="bounceRate"), Metric(name="averageSessionDuration"),
    ]
    prop_label = params.property_id or "default"

    rows_device  = _rows_to_list(client.run_report(RunReportRequest(
        property=prop, dimensions=[Dimension(name="deviceCategory")],
        metrics=shared_metrics, date_ranges=dr,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
    )))
    rows_country = _rows_to_list(client.run_report(RunReportRequest(
        property=prop, dimensions=[Dimension(name="country")],
        metrics=shared_metrics, date_ranges=dr,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=params.limit,
    )))

    if params.response_format == "json":
        return json.dumps({"property": prop_label, "devices": rows_device, "countries": rows_country}, indent=2)

    return "\n\n".join([
        _format_rows(rows_device,  "markdown", f"Dispositivi — {prop_label} ({params.start_date} → {params.end_date})"),
        _format_rows(rows_country, "markdown", f"Paesi — {prop_label} ({params.start_date} → {params.end_date})"),
    ])


@mcp.tool(
    name="ga4_get_pages_report",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ga4_get_pages_report(params: PageInput) -> str:
    """Pagine più visitate in GA4 con metriche di engagement. Supporta più property.

    Args:
        params: PageInput con property_id, start_date, end_date, limit, response_format, min_pageviews opzionale.

    Returns:
        str: Classifica pagine per pageviews.
    """
    client = _get_client()
    prop_label = params.property_id or "default"
    request = RunReportRequest(
        property=_resolve_property(params.property_id),
        dimensions=[Dimension(name="pagePath"), Dimension(name="pageTitle")],
        metrics=[
            Metric(name="screenPageViews"), Metric(name="totalUsers"),
            Metric(name="averageSessionDuration"), Metric(name="bounceRate"),
            Metric(name="engagementRate"),
        ],
        date_ranges=[_date_range(params.start_date, params.end_date)],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
        limit=params.limit,
    )
    rows = _rows_to_list(client.run_report(request))
    return _format_rows(rows, params.response_format, f"Top Pagine — {prop_label} ({params.start_date} → {params.end_date})")


@mcp.tool(
    name="ga4_get_conversions",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ga4_get_conversions(params: DateRangeInput) -> str:
    """Conversioni e eventi chiave GA4 per canale e per nome evento. Supporta più property.

    Args:
        params: DateRangeInput con property_id, start_date, end_date, limit, response_format.

    Returns:
        str: Report conversioni per canale e per evento.
    """
    client = _get_client()
    prop = _resolve_property(params.property_id)
    dr = [_date_range(params.start_date, params.end_date)]
    prop_label = params.property_id or "default"

    rows_channel = _rows_to_list(client.run_report(RunReportRequest(
        property=prop, dimensions=[Dimension(name="sessionDefaultChannelGroup")],
        metrics=[Metric(name="conversions"), Metric(name="sessions"), Metric(name="totalUsers")],
        date_ranges=dr,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="conversions"), desc=True)],
        limit=params.limit,
    )))
    rows_events = _rows_to_list(client.run_report(RunReportRequest(
        property=prop, dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="conversions"), Metric(name="eventCount")],
        date_ranges=dr,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="conversions"), desc=True)],
        limit=params.limit,
    )))

    if params.response_format == "json":
        return json.dumps({"property": prop_label, "by_channel": rows_channel, "by_event": rows_events}, indent=2)

    return "\n\n".join([
        _format_rows(rows_channel, "markdown", f"Conversioni per Canale — {prop_label} ({params.start_date} → {params.end_date})"),
        _format_rows(rows_events,  "markdown", "Conversioni per Evento"),
    ])


@mcp.tool(
    name="ga4_get_funnel",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ga4_get_funnel(params: FunnelInput) -> str:
    """Analisi funnel GA4 con drop-off tra step. Supporta più property.

    Args:
        params: FunnelInput con steps (lista di pagePaths), property_id, date range, response_format.

    Returns:
        str: Report funnel con utenti e % drop-off per ogni step.
    """
    client = _get_client()
    prop = _resolve_property(params.property_id)
    dr = [_date_range(params.start_date, params.end_date)]
    prop_label = params.property_id or "default"

    step_data = []
    for step_path in params.steps:
        response = client.run_report(RunReportRequest(
            property=prop,
            dimensions=[Dimension(name="pagePath")],
            metrics=[Metric(name="totalUsers"), Metric(name="screenPageViews")],
            date_ranges=dr,
            dimension_filter=FilterExpression(filter=Filter(
                field_name="pagePath",
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.BEGINS_WITH,
                    value=step_path,
                ),
            )),
        ))
        users = sum(int(r.metric_values[0].value) for r in response.rows) if response.rows else 0
        step_data.append({"step": step_path, "users": users})

    for i, step in enumerate(step_data):
        if i == 0:
            step["drop_off_pct"] = "—"
            step["conversion_from_prev"] = "—"
        else:
            prev, curr = step_data[i-1]["users"], step["users"]
            drop = round((1 - curr/prev)*100, 1) if prev > 0 else 0.0
            conv = round(curr/prev*100, 1) if prev > 0 else 0.0
            step["drop_off_pct"] = f"{drop}%"
            step["conversion_from_prev"] = f"{conv}%"

    if params.response_format == "json":
        return json.dumps({"property": prop_label, "funnel": step_data}, indent=2)

    lines = [f"## Funnel — {prop_label} ({params.start_date} → {params.end_date})\n"]
    lines.append("| Step | Pagina | Utenti | Conv. da precedente | Drop-off |")
    lines.append("|------|--------|--------|---------------------|----------|")
    for i, step in enumerate(step_data):
        lines.append(f"| {i+1} | `{step['step']}` | {step['users']:,} | {step['conversion_from_prev']} | {step['drop_off_pct']} |")

    if step_data[0]["users"] > 0:
        overall = round(step_data[-1]["users"] / step_data[0]["users"] * 100, 2)
        lines.append(f"\n**Tasso di completamento funnel: {overall}%**")

    return "\n".join(lines)


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    if TRANSPORT == "stdio":
        mcp.run()
    else:
        print(f"🚀 GA4 MCP Server avviato su porta {PORT}", file=sys.stderr)
        print(f"   Property configurate: {list(PROPERTIES.keys())}", file=sys.stderr)
        app = FastAPI()
        mcp_app = mcp.streamable_http_app()
        app.mount("/mcp", mcp_app)

        @app.get("/")
        async def root():
            return {"status": "ok", "server": "ga4_mcp"}

        uvicorn.run(app, host="0.0.0.0", port=PORT)
