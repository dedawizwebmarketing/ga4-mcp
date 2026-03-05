# GA4 MCP Server — Versione Remota 🌐

Server MCP GA4 deployabile su cloud, accessibile da **Claude Desktop** e **claude.ai** (browser).
Supporta **più property GA4** con un solo server.

---

## Deploy su Railway (gratuito)

### Passo 1 — Crea account GitHub
1. Vai su [github.com](https://github.com) → Sign up (gratis)
2. Crea un nuovo repository: **New repository** → nome `ga4-mcp` → Public → Create

### Passo 2 — Carica i file su GitHub
Dalla cartella del progetto sul tuo PC, apri cmd:
```cmd
cd C:\Users\DGTGLI83C\Downloads\ga4-mcp-remote

git init
git add .
git commit -m "GA4 MCP Server"
git remote add origin https://github.com/TUO_USERNAME/ga4-mcp.git
git push -u origin main
```

### Passo 3 — Deploy su Railway
1. Vai su [railway.app](https://railway.app) → Login with GitHub
2. **New Project** → **Deploy from GitHub repo** → seleziona `ga4-mcp`
3. Railway detecta automaticamente Python e fa il deploy

### Passo 4 — Configura le variabili d'ambiente su Railway
In Railway → il tuo progetto → **Variables** → aggiungi:

| Variabile | Valore |
|-----------|--------|
| `GA4_KEY_JSON` | (vedi sotto come ottenerlo) |
| `GA4_PROPERTY_ID` | `318515941` (la tua property default) |
| `GA4_PROPERTIES_MAP` | `sito_a=318515941,sito_b=987654321` (opzionale) |
| `MCP_TRANSPORT` | `streamable_http` |

#### Come ottenere GA4_KEY_JSON
Il file JSON della chiave non può essere caricato direttamente su Railway.
Convertilo in base64 con questo comando:

**Windows (PowerShell):**
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\Users\DGTGLI83C\Downloads\MCP\ga4-mcp-489309-38509944fc3e.json"))
```

Copia l'output (una stringa lunga) e incollala come valore di `GA4_KEY_JSON`.

### Passo 5 — Ottieni l'URL del server
In Railway → il tuo progetto → **Settings** → **Domains** → genera un dominio.
Sarà tipo: `https://ga4-mcp-production.up.railway.app`

---

## Configurazione per il team

### Su claude.ai (browser) — per ogni membro del team
1. Apri [claude.ai](https://claude.ai) → **Impostazioni** (icona in basso a sinistra)
2. **Integrazioni** → **Aggiungi integrazione**
3. Inserisci l'URL: `https://ga4-mcp-production.up.railway.app/mcp`
4. Nome: `GA4`
5. Salva → ora hanno accesso a tutti i tool GA4!

### Su Claude Desktop — per ogni membro del team
Nel file `claude_desktop_config.json` aggiungere:
```json
{
  "mcpServers": {
    "ga4": {
      "url": "https://ga4-mcp-production.up.railway.app/mcp"
    }
  }
}
```
Molto più semplice della versione locale — niente Python, niente chiavi JSON!

---

## Supporto Multi-Property

Con `GA4_PROPERTIES_MAP` puoi gestire più siti/clienti:

```
GA4_PROPERTIES_MAP=sito_aziendale=318515941,blog=123456789,ecommerce=987654321
```

Poi in Claude puoi chiedere:
- *"Mostrami le sessioni di sito_aziendale"*
- *"Confronta blog vs ecommerce negli ultimi 30 giorni"*
- *"Quali property sono disponibili?"* → usa `ga4_list_properties`

---

## Variabili d'ambiente

| Variabile | Obbligatoria | Descrizione |
|-----------|--------------|-------------|
| `GA4_KEY_JSON` | ✅ (cloud) | Chiave service account in base64 |
| `GA4_KEY_FILE` | ✅ (locale) | Percorso file JSON chiave |
| `GA4_PROPERTY_ID` | ✅ | Property ID default |
| `GA4_PROPERTIES_MAP` | ❌ | Mappa `nome=id` separati da virgola |
| `MCP_TRANSPORT` | ❌ | `streamable_http` (default) o `stdio` |
| `PORT` | ❌ | Porta HTTP (default: 8000, Railway la imposta auto) |

---

## Tool disponibili

| Tool | Descrizione |
|------|-------------|
| `ga4_list_properties` | Elenca property configurate |
| `ga4_get_overview` | Metriche generali |
| `ga4_get_channel_report` | Traffico per canale |
| `ga4_get_realtime` | Utenti attivi ora |
| `ga4_get_device_country_report` | Per dispositivo e paese |
| `ga4_get_pages_report` | Pagine più visitate |
| `ga4_get_conversions` | Conversioni per canale/evento |
| `ga4_get_funnel` | Analisi funnel con drop-off |
