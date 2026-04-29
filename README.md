# Entra ID Authentication & Authorization Demos

A Blazor Web App (.NET 8) that demonstrates two Microsoft Entra ID authentication patterns for accessing Azure Storage and Azure SQL Database — with a real-time log panel that exposes every token, claim, and auth step as it happens.

---

## 1. Concepts

### Authentication vs. Authorization

| | Authentication | Authorization |
|---|---|---|
| **Question answered** | *Who are you?* | *What are you allowed to do?* |
| **Mechanism** | Credentials verified by an Identity Provider (Entra ID) | Permissions checked by the resource (Storage, SQL) |
| **Result** | An **ID token** (identity proof) and/or an **access token** | Access granted or denied (HTTP 403) |

In Azure, **Entra ID** (formerly Azure AD) is the identity provider. It issues **OAuth 2.0 tokens** that Azure resources validate. Authentication proves identity; authorization is enforced by **RBAC role assignments** on the resource side (e.g., `Storage Blob Data Reader`).

### Service Principal

When you register an application in Entra ID, two objects are created:

1. **App Registration** — the global definition (Client ID, secrets, permissions)
2. **Service Principal** — the local identity object in your tenant

A service principal is *the app's identity*. It can authenticate using a **Client ID + Client Secret** (or certificate) without any user involved. This is called the **Client Credentials flow**:

```
App ──── Client ID + Secret ────► Entra ID
                                      │
                                      ▼
App ◄──── Access Token (app-only) ────┘
                                      │
App ──── Access Token ──────────► Azure Resource
```

The resulting token contains **application permissions** (not delegated). The `oid` and `sub` claims identify the service principal, and the `roles` claim lists its app roles. There is no user context.

### On-Behalf-Of (OBO) Pattern

OBO is a two-step delegation pattern:

1. **User signs in** — the app receives an ID token and an authorization code via OpenID Connect. The code is exchanged for a user access token scoped to the *app's own API*.
2. **App exchanges the user token** — the app presents the user's token to Entra ID along with the app's own credentials, requesting a *new* token scoped to a downstream resource (Storage, SQL). Entra ID issues a **delegated access token** that carries the user's identity.

```
User ──── Browser sign-in ────► Entra ID
                                    │
                                    ▼
App  ◄──── ID Token + Auth Code ────┘

App  ──── User Token + Client Secret ────► Entra ID  (OBO exchange)
                                               │
                                               ▼
App  ◄──── Delegated Access Token ─────────────┘
                                               │
App  ──── Delegated Token ──────────────► Azure Resource
                                          (acts as the user)
```

The delegated token contains **user claims** (`upn`, `name`, `oid`) and a `scp` (scope) claim like `user_impersonation`. The resource enforces authorization based on *the user's own RBAC assignments*, not the app's.

**Key difference**: With a service principal the app acts as itself; with OBO the app acts *as the signed-in user*. OBO provides an audit trail tied to the individual user.

---

## 2. How These Concepts Are Applied in the Code

### Project Structure

```
src/AuthenticationDemos.Web/
├── Program.cs                              ← DI wiring, auth middleware
├── appsettings.json                        ← All Azure configuration
├── Models/
│   ├── AzureResourcesOptions.cs            ← Typed config for Storage/SQL
│   ├── BlobItemModel.cs
│   ├── SqlTableInfo.cs
│   └── SqlQueryResult.cs
├── Services/
│   ├── IDemoLogger.cs / DemoLogger.cs      ← Real-time log service
│   ├── IStorageExplorer.cs / StorageExplorer.cs  ← Azure Storage SDK
│   ├── ISqlExplorer.cs / SqlExplorer.cs    ← Azure SQL with token auth
│   └── TokenHelper.cs                     ← JWT decoding for log panel
├── Components/
│   ├── Pages/
│   │   ├── Home.razor                      ← Landing page
│   │   ├── ServicePrincipalDemo.razor      ← Demo 1 (Client Credentials)
│   │   └── OnBehalfOfDemo.razor            ← Demo 2 (OBO)
│   ├── Shared/
│   │   ├── LogPanel.razor                  ← Color-coded log viewer
│   │   ├── StorageBrowser.razor            ← Container/blob navigation
│   │   └── SqlBrowser.razor                ← Table picker + query grid
│   └── Layout/
│       └── MainLayout.razor                ← Nav + sign-in/sign-out bar
```

### Demo 1: Service Principal — Where to Look

| Concept | File | What to look for |
|---------|------|-----------------|
| Creating the credential | `ServicePrincipalDemo.razor` line ~79 | `new ClientSecretCredential(tenantId, clientId, clientSecret)` |
| Requesting an app-only token | `ServicePrincipalDemo.razor` line ~89 | `credential.GetTokenAsync()` with scope `https://storage.azure.com/.default` |
| Decoding and logging JWT claims | `Services/TokenHelper.cs` | `JwtSecurityTokenHandler.ReadJwtToken()` — logs issuer, audience, every claim |
| Using the token with Azure SDK | `ServicePrincipalDemo.razor` line ~93 | `new BlobServiceClient(uri, credential)` — SDK handles token attachment |
| SQL token-based auth | `Services/SqlExplorer.cs` line ~103 | `connection.AccessToken = _accessToken` — sets the bearer token on `SqlConnection` |
| SQL injection prevention | `Services/SqlExplorer.cs` line ~73-77 | Table names validated against `INFORMATION_SCHEMA.TABLES` allowlist; `topN` is a `SqlParameter` |

**Flow in the code**: Click "Run Demo" → `ClientSecretCredential` is created → token requested for Storage scope → JWT decoded and all claims logged → `BlobServiceClient` created with that credential → same flow repeated for SQL with `https://database.windows.net/.default` scope.

### Demo 2: On Behalf Of — Where to Look

| Concept | File | What to look for |
|---------|------|-----------------|
| OpenID Connect sign-in setup | `Program.cs` line ~14 | `AddMicrosoftIdentityWebAppAuthentication()` — configures OIDC middleware |
| Enabling OBO token acquisition | `Program.cs` line ~15 | `.EnableTokenAcquisitionToCallDownstreamApi()` — registers `ITokenAcquisition` |
| Requiring authentication | `OnBehalfOfDemo.razor` line ~14 | `@attribute [Authorize]` — redirects anonymous users to sign-in |
| Logging the user's ID token claims | `OnBehalfOfDemo.razor` line ~97-101 | Iterates `user.Claims` from `AuthenticationState` |
| OBO token exchange | `OnBehalfOfDemo.razor` line ~110 | `TokenAcquisition.GetAccessTokenForUserAsync(storageScopes)` — triggers the OBO flow internally |
| Wrapping the OBO token for SDK use | `OnBehalfOfDemo.razor` line ~152-161 | `OboTokenCredential` — a simple `TokenCredential` wrapper around the pre-acquired token string |
| Sign-in / sign-out UI | `MainLayout.razor` | `<AuthorizeView>` with links to `MicrosoftIdentity/Account/SignIn` and `SignOut` |

**Flow in the code**: User clicks "Sign in" → OIDC redirect to Microsoft login → callback at `/signin-oidc` → user's claims displayed → click "Run Demo" → `ITokenAcquisition` exchanges the user's token for a delegated token (OBO) → JWT decoded and logged → `BlobServiceClient`/`SqlConnection` created with the delegated token.

### The Log Panel

The log panel (`Components/Shared/LogPanel.razor`) subscribes to `DemoLogger.OnLogEntry` and renders every entry in real time with color-coded levels:

- 🔵 **Info** — flow steps ("Acquiring token...", "Found 3 containers")
- 🟢 **Token** — token metadata (issuer, audience, expiry)
- 🟣 **Claim** — individual JWT claims (`appid`, `scp`, `upn`, `oid`, ...)
- 🟡 **Warning** — non-fatal issues (consent needed)
- 🔴 **Error** — failures with AADSTS codes or SDK errors

This gives the demo audience full visibility into what OAuth tokens look like, what claims they contain, and how the auth flow progresses.

---

## 3. How to Run It

### Prerequisites

- [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)
- An Azure subscription with:
  - An Azure Storage account (with at least one container and some blobs)
  - An Azure SQL Database (with at least one table containing data)
- Permissions to create Entra ID app registrations (or have an admin do it)

### Step 1: Register the Application in Entra ID

1. Go to [Azure Portal → Microsoft Entra ID → App registrations](https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps)
2. Click **New registration**
   - **Name**: `AuthenticationDemos` (or any name)
   - **Supported account types**: *Accounts in this organizational directory only* (Single tenant)
   - **Redirect URI**: Select *Web* → `https://localhost:7230/signin-oidc`
     > Adjust the port if yours is different. Check `Properties/launchSettings.json` for the actual HTTPS port.
3. Click **Register**
4. Note the **Application (client) ID** and **Directory (tenant) ID** from the Overview page

### Step 2: Create a Client Secret

1. In the app registration, go to **Certificates & secrets → Client secrets**
2. Click **New client secret**, provide a description, set expiry
3. Copy the **Value** immediately (it's only shown once)

### Step 3: Configure API Permissions

For **Demo 1 (Service Principal)** — add **Application permissions**:

1. Go to **API permissions → Add a permission**
2. **Azure Storage** → Application permissions → `user_impersonation` (if available) or this is handled via RBAC (skip API permissions, use role assignments in Step 4)
3. **Azure SQL Database** → same approach — authorization is done via RBAC/database roles, not API permissions

For **Demo 2 (OBO)** — add **Delegated permissions**:

1. **API permissions → Add a permission → APIs my organization uses**
2. Search **Azure Storage** → Delegated permissions → `user_impersonation` → Add
3. Search **Azure SQL Database** → Delegated permissions → `user_impersonation` → Add
4. Click **Grant admin consent** for your tenant

Additionally, expose an API scope (required for OBO):

1. Go to **Expose an API → Add a scope**
2. Accept the default Application ID URI (`api://<client-id>`)
3. Scope name: `access_as_user`, Admin consent display name: `Access app as user`
4. Click **Add scope**

### Step 4: Assign RBAC Roles on Azure Resources

#### Storage Account

For **Demo 1** (service principal access):
```bash
# Get the service principal object ID
SP_OBJECT_ID=$(az ad sp show --id <client-id> --query id -o tsv)

# Assign Storage Blob Data Reader
az role assignment create \
  --assignee $SP_OBJECT_ID \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>
```

For **Demo 2** (user access):
```bash
# Assign to the user who will sign in
az role assignment create \
  --assignee <user@domain.com> \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>
```

#### Azure SQL Database

1. Enable **Microsoft Entra authentication** on the SQL Server:
   - Azure Portal → SQL Server → Settings → Microsoft Entra ID → Set admin

2. Connect to the database as the Entra admin and run:

For **Demo 1** (service principal):
```sql
CREATE USER [AuthenticationDemos] FROM EXTERNAL PROVIDER;
ALTER ROLE db_datareader ADD MEMBER [AuthenticationDemos];
```
> Use the exact app registration name.

For **Demo 2** (user):
```sql
CREATE USER [user@domain.com] FROM EXTERNAL PROVIDER;
ALTER ROLE db_datareader ADD MEMBER [user@domain.com];
```

### Step 5: Update Configuration

Edit `src/AuthenticationDemos.Web/appsettings.json`:

```json
{
  "AzureAd": {
    "Instance": "https://login.microsoftonline.com/",
    "TenantId": "your-tenant-id-here",
    "ClientId": "your-client-id-here",
    "ClientSecret": "your-client-secret-here",
    "CallbackPath": "/signin-oidc",
    "SignedOutCallbackPath": "/signout-callback-oidc"
  },
  "AzureResources": {
    "StorageAccountName": "your-storage-account",
    "SqlServer": "your-server.database.windows.net",
    "SqlDatabase": "your-database"
  }
}
```

> **Security note**: For real projects, never commit secrets. Use `dotnet user-secrets`, environment variables, or Azure Key Vault. For this demo, `appsettings.json` is acceptable for local use only.

### Step 6: Build and Run

```bash
cd src/AuthenticationDemos.Web
dotnet run
```

Open the URL shown in the terminal (typically `https://localhost:7230`).

### Step 7: Run the Demos

**Demo 1 — Service Principal**:
1. Navigate to `/service-principal`
2. Click **▶ Run Demo**
3. Watch the log panel — it shows the client credentials token acquisition, decoded JWT claims (`appid`, `aud`, `iss`, `oid`), and the results from Storage and SQL

**Demo 2 — On Behalf Of**:
1. Navigate to `/on-behalf-of`
2. You'll be redirected to Microsoft sign-in
3. Sign in and consent to the requested permissions
4. Click **▶ Run Demo**
5. Watch the log panel — it shows your ID token claims (`name`, `preferred_username`, `oid`), the OBO token exchange, and delegated access token claims (`scp: user_impersonation`, `upn`)

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `AADSTS7000215: Invalid client secret` | Wrong or expired secret | Regenerate in App registrations → Certificates & secrets |
| `AADSTS65001: User or admin has not consented` | Missing consent for delegated permissions | Click "Grant admin consent" in API permissions, or sign out and sign in again |
| `403 Forbidden` on Storage | Missing RBAC role | Assign `Storage Blob Data Reader` to the SP/user on the storage account |
| `Login failed for user '<token-identified principal>'` on SQL | User not created in database | Run the `CREATE USER ... FROM EXTERNAL PROVIDER` SQL commands |
| `AADSTS50011: Reply URL does not match` | Redirect URI mismatch | Ensure the port in the app registration matches your `launchSettings.json` |

---

## License

This is a demo project for educational purposes.
