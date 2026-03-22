# Alpaca RL Web UI

Modern web interface for the Alpaca RL Suite with Keycloak authentication.

## Features

- **Authentication**: Secured with Keycloak OAuth2/OIDC
- **Dashboard**: System overview and activity feed
- **Training**: Manage Kaggle training jobs
- **Approvals**: Review and approve policy promotions
- **Policies**: Browse and manage RL policies
- **Datasets**: Create and manage training datasets
- **Monitoring**: System health and metrics

## Architecture

### Backend (FastAPI)
- JWT token validation using Keycloak public keys
- API proxy to microservices with token forwarding
- Authentication endpoints for frontend configuration

### Frontend (React + TypeScript)
- Keycloak JavaScript adapter for OIDC flow
- Automatic token refresh
- Protected routes requiring authentication
- User profile display and logout

## Authentication Flow

1. User navigates to `https://ml4t.nelsonjohns.com`
2. Frontend fetches Keycloak config from `/api/auth/config`
3. Keycloak adapter initializes with `login-required`
4. User is redirected to Keycloak login page
5. After successful login, user is redirected back with authorization code
6. Keycloak adapter exchanges code for JWT tokens (using PKCE)
7. Frontend stores tokens and includes them in API requests
8. Backend validates JWT on each API call
9. Tokens are automatically refreshed before expiry

## Environment Variables

### Required
```bash
KEYCLOAK_URL=https://auth.nelsonjohns.com
KEYCLOAK_REALM=admin
KEYCLOAK_CLIENT_ID=alpaca-rl-web-ui
```

### Optional
```bash
WEB_UI_PORT=3200
KAGGLE_SERVICE_URL=http://kaggle-orchestrator:8011
BACKTEST_SERVICE_URL=http://backtest:8001
RL_TRAIN_SERVICE_URL=http://rl-train:8004
DATASET_SERVICE_URL=http://dataset-builder:8003
DASHBOARD_SERVICE_URL=http://dashboard:8020
GRAFANA_URL=http://grafana:3000
GRAFANA_EXTERNAL_URL=http://localhost:3100
```

## Setup

### 1. Configure Keycloak Client

Follow the detailed guide in `/docs/KEYCLOAK_SETUP.md` to:
- Create a client in Keycloak
- Configure redirect URIs
- Create users and assign roles

### 2. Build and Deploy

```bash
# Build the Docker image
cd /home/noslen/alpaca-rl-suite
docker-compose -f infra/docker-compose.yml build web-ui

# Start the service
docker-compose -f infra/docker-compose.yml up -d web-ui
```

### 3. Access the Application

Navigate to `https://ml4t.nelsonjohns.com` and log in with your Keycloak credentials.

## Development

### Local Development

```bash
# Backend
cd services/web-ui
pip install -r requirements.txt
uvicorn main:app --reload --port 3200

# Frontend
cd services/web-ui/frontend
npm install
npm run dev
```

### Environment Setup

For local development, create a `.env` file:

```bash
KEYCLOAK_URL=https://auth.nelsonjohns.com
KEYCLOAK_REALM=admin
KEYCLOAK_CLIENT_ID=alpaca-rl-web-ui
```

And update the Keycloak client to include `http://localhost:3200/*` in valid redirect URIs.

## Security

### JWT Validation
- Tokens are validated using Keycloak's public keys (JWKS)
- Signature, audience, issuer, and expiration are verified
- Invalid tokens result in 401 Unauthorized responses

### Token Forwarding
- Authentication tokens are forwarded to backend microservices
- Services can validate tokens independently if needed

### PKCE
- Proof Key for Code Exchange is enabled for enhanced security
- Protects against authorization code interception attacks

### Token Refresh
- Access tokens are automatically refreshed before expiration
- Refresh happens silently without user interaction
- Failed refresh triggers re-authentication

## API Endpoints

### Authentication
- `GET /api/auth/config` - Keycloak configuration (public)
- `GET /api/auth/userinfo` - Current user information (protected)

### Service Proxy
- `GET/POST/PUT/DELETE /api/{service}/{path}` - Proxy to microservices (protected)

### Health
- `GET /api/health` - Service health check (public)

## Troubleshooting

### TypeScript Errors During Development
The `keycloak-js` module errors are expected until `npm install` is run. These are resolved during the Docker build.

### Authentication Loop
If users are stuck in a redirect loop:
1. Clear browser cookies and local storage
2. Verify Keycloak client redirect URIs match exactly
3. Check browser console for errors

### Token Validation Failures
If API calls return 401 errors:
1. Verify Keycloak URL is accessible from the container
2. Check that realm and client ID are correct
3. Ensure Keycloak public keys can be fetched

### CORS Errors
If you see CORS errors in the browser:
1. Add your domain to Web Origins in Keycloak client settings
2. Verify CORS middleware is configured correctly in FastAPI

## Files Structure

```
services/web-ui/
├── main.py                 # FastAPI backend
├── auth.py                 # Authentication middleware
├── requirements.txt        # Python dependencies
├── Dockerfile             # Multi-stage build
├── frontend/
│   ├── src/
│   │   ├── auth/
│   │   │   ├── keycloak.ts        # Keycloak instance
│   │   │   └── AuthProvider.tsx   # Auth context
│   │   ├── api/
│   │   │   └── client.ts          # API client with auth
│   │   ├── components/
│   │   │   ├── Sidebar.tsx        # Navigation + user profile
│   │   │   └── LoadingScreen.tsx  # Auth loading state
│   │   ├── pages/                 # Application pages
│   │   ├── App.tsx                # Main app component
│   │   └── main.tsx               # Entry point
│   └── package.json
└── README.md
```

## Next Steps

- Implement role-based access control (RBAC) in UI
- Add role checks in backend endpoints
- Configure additional identity providers in Keycloak
- Set up multi-factor authentication (MFA)
- Implement audit logging for authentication events
