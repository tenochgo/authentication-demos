# AuthenticationDemos.PythonJs

Python + vanilla JavaScript implementation of the same authentication demos as `AuthenticationDemos.Web`:

- Demo 1: Service Principal (client credentials)
- Demo 2: On-Behalf-Of (user sign-in + delegated access)

## Configuration

Use the same `appsettings` input parameters as the .NET app.

1. Copy `appsettings.json.template` to `appsettings.json`
2. Fill in all values

## Run locally

```bash
cd src/AuthenticationDemos.PythonJs
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5000`

## Notes

- OBO sign-in endpoint: `/MicrosoftIdentity/Account/SignIn`
- OIDC callback path is read from `AzureAd:CallbackPath`
- Sign-out callback path is read from `AzureAd:SignedOutCallbackPath`
- SQL uses Azure AD access token via ODBC Driver 18 for SQL Server
