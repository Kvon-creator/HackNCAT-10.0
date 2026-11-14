import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type AuthenticationResult,
  type Configuration,
  type SilentRequest,
} from "@azure/msal-browser";

const clientId = import.meta.env.VITE_MS_CLIENT_ID;
const tenantId = import.meta.env.VITE_MS_TENANT_ID;
const apiScope = import.meta.env.VITE_MS_API_SCOPE;

function required(value: string | undefined, name: string): string {
  if (!value?.trim()) throw new Error(`Missing Microsoft configuration: ${name}`);
  return value.trim();
}

let clientPromise: Promise<PublicClientApplication> | undefined;

function getClient(): Promise<PublicClientApplication> {
  if (!clientPromise) {
    const config: Configuration = {
      auth: {
        clientId: required(clientId, "VITE_MS_CLIENT_ID"),
        authority: `https://login.microsoftonline.com/${required(tenantId, "VITE_MS_TENANT_ID")}`,
        redirectUri: window.location.origin,
      },
      cache: { cacheLocation: "sessionStorage" },
    };
    const client = new PublicClientApplication(config);
    clientPromise = client.initialize().then(async () => {
      const result = await client.handleRedirectPromise();
      if (result?.account) client.setActiveAccount(result.account);
      return client;
    });
  }
  return clientPromise;
}

function getAccount(client: PublicClientApplication): AccountInfo | null {
  return client.getActiveAccount() ?? client.getAllAccounts()[0] ?? null;
}

export async function getCurrentAccount(): Promise<AccountInfo | null> {
  return getAccount(await getClient());
}

export async function signIn(): Promise<AccountInfo> {
  const client = await getClient();
  const account = getAccount(client);
  if (!account) {
    const result = await client.loginPopup({ scopes: ["openid", "profile"] });
    if (!result.account) throw new Error("Microsoft sign-in returned no account");
    client.setActiveAccount(result.account);
    return result.account;
  }
  try {
    const result = await client.acquireTokenSilent({ scopes: ["openid", "profile"], account });
    client.setActiveAccount(result.account);
    return result.account;
  } catch (error) {
    if (!(error instanceof InteractionRequiredAuthError)) throw error;
    const result = await client.loginPopup({ scopes: ["openid", "profile"] });
    if (!result.account) throw new Error("Microsoft sign-in returned no account");
    client.setActiveAccount(result.account);
    return result.account;
  }
}

async function acquireApiToken(interactive: boolean): Promise<AuthenticationResult> {
  const client = await getClient();
  const scopes = [required(apiScope, "VITE_MS_API_SCOPE")];
  const account = getAccount(client);
  const request: SilentRequest = { scopes, ...(account ? { account } : {}) };
  try {
    const result = await client.acquireTokenSilent(request);
    client.setActiveAccount(result.account);
    return result;
  } catch (error) {
    if (!interactive || !(error instanceof InteractionRequiredAuthError)) throw error;
    const result = await client.acquireTokenPopup({ scopes, ...(account ? { account } : {}) });
    client.setActiveAccount(result.account);
    return result;
  }
}

/** Returns an AggieConnect API access token, never a Microsoft Graph token. */
export async function getApiToken(): Promise<string> {
  try {
    return (await acquireApiToken(false)).accessToken;
  } catch (error) {
    if (!(error instanceof InteractionRequiredAuthError)) throw error;
    return (await acquireApiToken(true)).accessToken;
  }
}

export async function signOut(): Promise<void> {
  const client = await getClient();
  const account = getAccount(client);
  await client.logoutPopup({ ...(account ? { account } : {}), postLogoutRedirectUri: window.location.origin });
}
