# AuthenticationDemos.PythonJs

A hands-on tutorial app that demonstrates two authentication patterns every Azure web app developer needs to understand. Built with Python (Flask) and vanilla JavaScript, it mirrors the .NET (`AuthenticationDemos.Web`) implementation so you can compare how the same patterns look across two stacks.

---

## What This App Teaches

When your web app needs to access Azure services (Storage, SQL, Key Vault, etc.), you have to decide *whose identity* the call runs under. The two demos here show the two most common answers.

### Pattern 1 — Service Principal (Client Credentials Flow)

The app authenticates **as itself** using a Client ID and Client Secret registered in Microsoft Entra ID. No user is involved. The access token is issued to the application's identity, so Azure resources see the app — not any individual person.

**When to use this:** background jobs, scheduled tasks, server-to-server calls, or any operation that should run under the app's own fixed permissions regardless of who triggered it.

**Where to look in the code:**
- `create_service_principal_credential()` — wraps `ClientSecretCredential` from `azure-identity`
- `run_service_principal()` (`/api/service-principal/run`) — acquires tokens for Storage and SQL and logs every claim in the token

### Pattern 3 — Foundry Chat (Service Principal + Entra ID Token, No API Key)

The service principal authenticates to **Azure AI Foundry** using the exact same `ClientSecretCredential` used in Pattern 1 — but instead of Storage or SQL, it targets the Azure Cognitive Services scope. No API key is passed anywhere. Access is controlled by Azure RBAC.

**When to use this:** any time your application calls an AI model endpoint. Entra ID tokens are short-lived and auditable; model API keys are long-lived shared secrets that bypass all RBAC controls.

**How it works:**
1. `ClientSecretCredential` presents the app's client ID + secret to Entra.
2. `get_bearer_token_provider()` wraps the credential and lazily fetches a token for the `https://ai.azure.com/.default` scope on each request (auto-renewing before expiry).
3. The `openai.OpenAI` client attaches that bearer token to each API request.
4. Foundry validates the token and checks that the service principal holds the required role (`Cognitive Services OpenAI User` or `Azure AI User`) on the resource.

**Required RBAC role:** assign **`Azure AI Foundry User`** to the service principal on your Foundry project (or on the parent Azure AI Services account).

> **Role clarification:**
> - `Cognitive Services OpenAI User` — only applies to dedicated **Azure OpenAI Service** resources (`.openai.azure.com`). It does not work on the newer unified Azure AI Services accounts (`.services.ai.azure.com`).
> - `Azure AI Foundry User` — the correct role for Azure AI Services accounts and Foundry projects. You can assign it at the **project scope** (not just the full account) to limit the service principal to only that project's deployments.

**Where to look in the code:**
- `get_foundry_client()` — creates an `OpenAI` client with `get_bearer_token_provider(ClientSecretCredential, "https://ai.azure.com/.default")`; the docstring explains the token flow
- `chat_message()` (`POST /api/chat/message`) — builds the conversation history, calls `client.complete()`, returns the reply and usage metrics
- `get_chat_history()` — stores per-session message history in server-side state so the model gets full context on every turn
- `clear_chat_history()` (`DELETE /api/chat/history`) — resets context for a fresh conversation

---

### Pattern 2 — Delegated Access (On Behalf Of the Signed-In User)

The user signs in through Microsoft Entra ID and the app then acquires access tokens that carry **the user's identity** when calling downstream Azure services. Azure sees the actual user — their RBAC assignments and audit trail apply.

The sign-in uses the **OpenID Connect Authorization Code Flow with PKCE**, implemented manually with MSAL so every step is visible.

**When to use this:** any operation where the result depends on who the user is, where you want per-user audit logs in Azure, or where RBAC is scoped to individual identities.

**Where to look in the code:**
- `signin()` — initiates the PKCE auth code flow and redirects the user to Entra's login page
- `signin_callback()` — receives the auth code from Entra, exchanges it for tokens, and saves the token cache to the session
- `acquire_delegated_token()` — silently retrieves access tokens for Storage or SQL using the cached refresh token
- `run_obo()` (`/api/on-behalf-of/run`) — demonstrates the full delegated token acquisition and logs the claims

---

## How the Pieces Fit Together

### Microsoft Entra ID

Entra ID (formerly Azure Active Directory) is the identity platform that issues every token in this app. Both flows call Entra's token endpoint:

- **Service principal flow:** the app sends its client credentials to `/oauth2/v2.0/token` and receives an access token scoped to the application identity.
- **Delegated flow:** the user is sent to Entra's login UI, authenticates there, and Entra issues an ID token (who the user is), an access token, and a refresh token. The refresh token lets the app fetch new access tokens silently on future requests without involving the user again.

Entra validates permissions — via API permissions and Azure RBAC — before issuing any token. If the app or user does not have the required permissions, the token request fails before the Azure resource ever sees the request.

### MSAL (Microsoft Authentication Library)

This app uses [MSAL for Python](https://github.com/AzureAD/microsoft-authentication-library-for-python) to manage the delegated flow. MSAL handles:

- Building the redirect URL for Entra's login page (with PKCE challenge generation)
- Validating the `state` parameter on the callback (CSRF protection)
- Exchanging the authorization code for tokens
- Caching tokens in a serializable per-session store and using the refresh token to silently acquire new access tokens without re-prompting the user

### Azure App Service Easy Auth

When you deploy a web app to **Azure App Service**, you can enable **Easy Auth** from the portal with zero code changes. Easy Auth intercepts every incoming request, handles the redirect to Entra, validates tokens, and injects the authenticated user's claims into request headers — your application code never touches authentication.

This tutorial implements that same flow **manually with MSAL** so you can see exactly what Easy Auth automates for you:

| What Easy Auth does automatically | Where this app does it in code |
|---|---|
| Redirect unauthenticated users to Entra login | `signin()` |
| Exchange the authorization code for tokens | `signin_callback()` |
| Store and refresh tokens between requests | `load_token_cache()` / `save_token_cache()` |
| Expose the user's identity to application code | `state["user"]` populated in `signin_callback()` |

Understanding the manual flow first makes Easy Auth's value immediately obvious: it eliminates all of the above boilerplate and lets your app logic start at "the user is already authenticated."

---

## Setup

### 1. Entra ID App Registration

In the [Azure portal](https://portal.azure.com), your app registration needs:

| Setting | Value |
|---|---|
| Platform | Web |
| Redirect URI | `http://localhost:5001/signin-oidc` |
| API permissions | `https://storage.azure.com/user_impersonation` (delegated) |
| API permissions | `https://database.windows.net/user_impersonation` (delegated) |

### 2. Configuration File

```bash
cp appsettings.json.template appsettings.json
```

Fill in all values from your Entra app registration and Azure resource names.

### 3. Foundry Chat Setup

To use the chat demo:

1. **Create an Azure AI Foundry project** in the [Azure portal](https://ai.azure.com) and deploy a model (e.g., `gpt-4o-mini`).

2. **Get the inference endpoint** — in your Foundry project, go to **Models + endpoints** → select your deployed model → copy the "Target URI" (ends in `/models`).

3. **Grant the service principal access** — on your Azure AI Foundry resource, assign the **`Cognitive Services OpenAI User`** (or `Azure AI User`) RBAC role to the app registration service principal. This is what allows the service principal to call the model using its Entra ID token.

4. **Fill in `appsettings.json`:**
   ```json
   "Foundry": {
     "Endpoint": "https://<your-project>.services.ai.azure.com/models",
     "ModelDeployment": "gpt-4o-mini",
     "SystemPrompt": "You are a helpful assistant. Be concise and clear."
   }
   ```

> **Why no API key?** Model API keys are long-lived shared secrets — anyone who has one can call your model with no audit trail. Entra ID tokens are scoped (specific resource only), short-lived (default 1 hour), and leave a full audit log in Entra sign-in logs. The `openai` SDK accepts a token provider callable as `api_key` and automatically handles token acquisition and renewal.

> **Scope change from legacy**: The correct scope for the OpenAI SDK `/openai/v1/` endpoint is `https://ai.azure.com/.default`. The older Azure AI Inference SDK used `https://cognitiveservices.azure.com/.default` — these are not interchangeable.

### 4. macOS Prerequisites (ODBC Driver for SQL)

```bash
brew install unixodbc
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18
```

---

## Run Locally

```bash
cd src/AuthenticationDemos.PythonJs
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5001` in your browser.

> The app binds to `127.0.0.1:5001`. Port 5001 avoids a conflict with macOS AirPlay Receiver, which occupies port 5000 on the IPv6 loopback address. The redirect URI is always built from `AzureAd:RedirectBaseUrl` in `appsettings.json` so it consistently says `localhost` regardless of which IP the browser used to reach the server.

---

## Dependencies

| Package | Purpose |
|---|---|
| `flask` | Web framework |
| `msal` | OpenID Connect auth code flow + per-session token cache |
| `azure-identity` | `ClientSecretCredential` for the service principal flow |
| `azure-storage-blob` | Azure Blob Storage client |
| `openai` | Azure AI Foundry chat completions via OpenAI v1 API (`/openai/v1/`) |
| `pyodbc` | SQL Server via ODBC Driver 18 for SQL Server |
| `PyJWT` | Decode JWT claims for display in the log panel |
