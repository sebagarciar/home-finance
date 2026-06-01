const TOKEN_KEY = "hf_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// Called when any API request receives a 401. The App component registers
// this callback so it can immediately switch to the login screen.
let _onUnauthorized: (() => void) | null = null;

export function registerUnauthorizedHandler(cb: () => void): void {
  _onUnauthorized = cb;
}

export function triggerUnauthorized(): void {
  _onUnauthorized?.();
}
