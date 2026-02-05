# AI Power Grid API and SDK for Bots

Reference for bots and agents that want to interface with AI Power Grid (AIPG) for text or image generation.

## API base and auth

- **Base URL:** `https://api.aipowergrid.io/api`
- **Full OpenAPI/Swagger:** https://api.aipowergrid.io/api/swagger.json
- **Auth:** Send your API key in the `apikey` header (or `Authorization` where documented). Get a key at **https://dashboard.aipowergrid.io** (or aipowergrid.io).

## Text generation (for chatbots / agents)

1. **Submit request (async)**  
   `POST /v2/generate/text/async`  
   Headers: `apikey`, `Client-Agent`.  
   Body: `GenerationInputKobold` — includes `prompt`, optional `params` (e.g. `max_length`, `max_context_length`, `temperature`, `rep_pen`, `top_p`, `top_k`, `stop_sequence`), optional `models` array to restrict which models can be used.

2. **Poll for result**  
   `GET /v2/generate/text/status/{id}`  
   Returns status and, when done, the generated text in `generations[].text`. Use `/v2/generate/text/check/{id}` for a lightweight check without full response.

3. **Cancel if needed**  
   `DELETE /v2/generate/text/status/{id}`

Async requests live ~20 minutes; if no workers are available the request is still accepted and may be fulfilled later.

## Image generation

- **Submit:** `POST /v2/generate/async` with `GenerationInputStable` (prompt, params, etc.).
- **Check/retrieve:** `GET /v2/generate/check/{id}` or `GET /v2/generate/status/{id}`.
- **Cancel:** `DELETE /v2/generate/status/{id}`.

## Useful endpoints for bots

- **Verify user / lookup by API key:** `GET /v2/find_user` with `apikey` header.
- **List active models (text or image):** `GET /v2/status/models?type=text` or `type=image`.
- **Horde status / maintenance:** `GET /v2/status/modes`.
- **Performance / queue:** `GET /v2/status/performance`.
- **News:** `GET /v2/status/news`.

## Python SDK (grid-sdk)

- **Repo:** https://github.com/AIPowerGrid/grid-sdk  
- **About:** Python library to interact with AI Power Grid’s free generative AI APIs. Simplifies requesting images, text, and image interrogation without building raw HTTP requests.
- **Docs:** See the repo and its docs/; the SDK wraps the same API described in the swagger.
- **Use case:** Bots can use the SDK for text/image generation instead of calling the REST API directly.

## Quick links

- **API keys / dashboard:** https://dashboard.aipowergrid.io  
- Swagger (full API): https://api.aipowergrid.io/api/swagger.json  
- Grid SDK (Python): https://github.com/AIPowerGrid/grid-sdk  
- AI Power Grid: https://aipowergrid.io  
