import { fetchJsonOrThrow } from "./runtime_validation";
import { resilientFetch } from "./resilient_fetch";
import { getRuntimeLocale } from "../../lib/i18n/config";

type JsonRecord = Record<string, unknown>;
type PasskeyAction = "authenticate" | "register";

function localized(ja: string, en: string): string {
  return getRuntimeLocale() === "en" ? en : ja;
}

export class PasskeyCancelledError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PasskeyCancelledError";
  }
}

function base64UrlToArrayBuffer(value: string): ArrayBuffer {
  const padding = "=".repeat((4 - (value.length % 4 || 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

function arrayBufferToBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function creationOptionsFromJson(raw: JsonRecord): CredentialCreationOptions {
  const publicKey = (raw.publicKey || raw) as JsonRecord;
  const user = (publicKey.user || {}) as JsonRecord;
  const excludeCredentials = Array.isArray(publicKey.excludeCredentials)
    ? publicKey.excludeCredentials.map((item) => {
        const descriptor = item as JsonRecord;
        return {
          ...descriptor,
          id: base64UrlToArrayBuffer(String(descriptor.id || "")),
          type: String(descriptor.type || "public-key") as PublicKeyCredentialType
        };
      })
    : undefined;

  return {
    publicKey: {
      ...publicKey,
      challenge: base64UrlToArrayBuffer(String(publicKey.challenge || "")),
      user: {
        id: base64UrlToArrayBuffer(String(user.id || "")),
        name: String(user.name || ""),
        displayName: String(user.displayName || user.name || "")
      },
      excludeCredentials
    } as PublicKeyCredentialCreationOptions
  };
}

function requestOptionsFromJson(raw: JsonRecord): CredentialRequestOptions {
  const publicKey = (raw.publicKey || raw) as JsonRecord;
  const allowCredentials = Array.isArray(publicKey.allowCredentials)
    ? publicKey.allowCredentials.map((item) => {
        const descriptor = item as JsonRecord;
        return {
          ...descriptor,
          id: base64UrlToArrayBuffer(String(descriptor.id || "")),
          type: String(descriptor.type || "public-key") as PublicKeyCredentialType
        };
      })
    : undefined;

  return {
    publicKey: {
      ...publicKey,
      challenge: base64UrlToArrayBuffer(String(publicKey.challenge || "")),
      allowCredentials
    } as PublicKeyCredentialRequestOptions
  };
}

function publicKeyCredentialToJson(credential: PublicKeyCredential): JsonRecord {
  const response = credential.response as AuthenticatorResponse & {
    attestationObject?: ArrayBuffer;
    authenticatorData?: ArrayBuffer;
    signature?: ArrayBuffer;
    userHandle?: ArrayBuffer | null;
    getTransports?: () => string[];
  };

  const payload: JsonRecord = {
    id: credential.id,
    rawId: arrayBufferToBase64Url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: arrayBufferToBase64Url(response.clientDataJSON)
    }
  };

  const responsePayload = payload.response as JsonRecord;
  if (response.attestationObject) {
    responsePayload.attestationObject = arrayBufferToBase64Url(response.attestationObject);
  }
  if (typeof response.getTransports === "function") {
    responsePayload.transports = response.getTransports();
  }
  if (response.authenticatorData) {
    responsePayload.authenticatorData = arrayBufferToBase64Url(response.authenticatorData);
  }
  if (response.signature) {
    responsePayload.signature = arrayBufferToBase64Url(response.signature);
  }
  if (response.userHandle != null && response.userHandle.byteLength > 0) {
    responsePayload.userHandle = arrayBufferToBase64Url(response.userHandle);
  }

  return payload;
}

async function requestJson(url: string, init?: RequestInit): Promise<JsonRecord> {
  const { payload } = await fetchJsonOrThrow<JsonRecord>(
    url,
    {
      credentials: "same-origin",
      ...init
    },
    {
      defaultMessage: localized("認証に失敗しました。", "Authentication failed."),
      hasApplicationError: (data) => data.status === "fail",
      fetchImpl: resilientFetch
    }
  );
  return payload;
}

function getErrorName(error: unknown): string {
  return typeof error === "object" && error !== null && "name" in error
    ? String((error as { name?: unknown }).name || "")
    : "";
}

function isPasskeyCancellationError(error: unknown): boolean {
  const rawMessage = (
    typeof error === "object" &&
    error !== null &&
    "message" in error
  )
    ? (error as { message?: unknown }).message
    : error;
  const errorName = getErrorName(error);
  const message = String(rawMessage || "").toLowerCase();
  return (
    errorName === "NotAllowedError" ||
    errorName === "AbortError" ||
    message.includes("the operation either timed out or was not allowed") ||
    message.includes("timed out or was not allowed")
  );
}

function normalizePasskeyBrowserError(error: unknown, action: PasskeyAction): Error {
  if (isPasskeyCancellationError(error)) {
    return new PasskeyCancelledError(
      action === "authenticate"
        ? localized("Passkey認証はキャンセルされました。メールまたはGoogleでも続けられます。", "Passkey authentication was canceled. You can continue with email or Google.")
        : localized("Passkey登録はキャンセルされました。必要なときにもう一度お試しください。", "Passkey registration was canceled. Try again whenever you are ready.")
    );
  }

  const errorName = getErrorName(error);

  if (errorName === "SecurityError") {
    return new Error(
      action === "authenticate"
        ? localized("このサイトのPasskeyは利用できません。HTTPSで接続しているか確認してください。", "Passkeys are unavailable on this site. Make sure you are connected over HTTPS.")
        : localized("このサイトへのPasskey登録はできません。HTTPSで接続しているか確認してください。", "A passkey cannot be registered for this site. Make sure you are connected over HTTPS.")
    );
  }

  if (errorName === "NotSupportedError") {
    return new Error(localized("このデバイスまたはブラウザではPasskeyがサポートされていません。", "Passkeys are not supported on this device or browser."));
  }

  if (error instanceof Error) {
    return error;
  }

  return new Error(
    action === "authenticate"
      ? localized("Passkey認証に失敗しました。", "Passkey authentication failed.")
      : localized("Passkey登録に失敗しました。", "Passkey registration failed.")
  );
}

export function browserSupportsPasskeys(): boolean {
  return typeof window !== "undefined" && typeof window.PublicKeyCredential !== "undefined";
}

export async function authenticateWithPasskey(): Promise<JsonRecord> {
  if (!browserSupportsPasskeys()) {
    throw new Error(localized("このブラウザではPasskeyを利用できません。", "Passkeys are unavailable in this browser."));
  }

  const optionsPayload = await requestJson("/api/passkeys/authenticate/options", {
    method: "POST"
  });
  const requestOptions = requestOptionsFromJson(optionsPayload);
  let credential: Credential | null;
  try {
    credential = await navigator.credentials.get(requestOptions);
  } catch (error) {
    throw normalizePasskeyBrowserError(error, "authenticate");
  }

  if (!(credential instanceof PublicKeyCredential)) {
    throw new PasskeyCancelledError(localized("Passkey認証はキャンセルされました。メールまたはGoogleでも続けられます。", "Passkey authentication was canceled. You can continue with email or Google."));
  }

  return requestJson("/api/passkeys/authenticate/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credential: publicKeyCredentialToJson(credential) })
  });
}

export async function registerPasskey(label?: string): Promise<JsonRecord> {
  if (!browserSupportsPasskeys()) {
    throw new Error(localized("このブラウザではPasskeyを利用できません。", "Passkeys are unavailable in this browser."));
  }

  const optionsPayload = await requestJson("/api/passkeys/register/options", {
    method: "POST"
  });
  const creationOptions = creationOptionsFromJson(optionsPayload);
  let credential: Credential | null;
  try {
    credential = await navigator.credentials.create(creationOptions);
  } catch (error) {
    throw normalizePasskeyBrowserError(error, "register");
  }

  if (!(credential instanceof PublicKeyCredential)) {
    throw new PasskeyCancelledError(localized("Passkey登録はキャンセルされました。必要なときにもう一度お試しください。", "Passkey registration was canceled. Try again whenever you are ready."));
  }

  return requestJson("/api/passkeys/register/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      credential: publicKeyCredentialToJson(credential),
      label: label || null
    })
  });
}
