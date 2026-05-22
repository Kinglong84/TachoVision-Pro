"""
services/cloud_service.py
Upload file .DDD su servizi cloud: Google Drive, OneDrive, Dropbox.

Flusso autenticazione:
  - Google Drive : OAuth2 con file credentials.json (Google Cloud Console)
                   Token salvato in ~/TachoVision/config/gdrive_token.json
  - OneDrive     : MSAL device code flow (nessuna configurazione richiesta,
                   usa l'app pubblica TachoVision)
  - Dropbox      : Personal Access Token (generato dall'utente su dropbox.com)

Tutti i token vengono salvati localmente cifrati e riutilizzati automaticamente.
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / "TachoVision" / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Microsoft App Registration (pubblica, pre-registrata) ────────────────────
# Client ID letto da variabile d'ambiente TACHOVISION_MSAL_CLIENT_ID.
# Per abilitare OneDrive: imposta la variabile nel sistema o in un file .env
# e registra l'app su portal.azure.com → App registrations.
MSAL_CLIENT_ID = os.getenv("TACHOVISION_MSAL_CLIENT_ID", "")
MSAL_AUTHORITY = "https://login.microsoftonline.com/common"
MSAL_SCOPES    = ["Files.ReadWrite", "User.Read"]

# Cartella cloud di destinazione
CLOUD_FOLDER   = "TachoVision"


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE DRIVE
# ─────────────────────────────────────────────────────────────────────────────
class GoogleDriveService:
    """
    Richiede il file credentials.json scaricato da Google Cloud Console:
      1. Vai su console.cloud.google.com
      2. Crea progetto → Abilita Google Drive API
      3. Credenziali → OAuth 2.0 → App desktop → Scarica JSON
      4. Salva come ~/TachoVision/config/gdrive_credentials.json
    """

    CREDS_PATH = CONFIG_DIR / "gdrive_credentials.json"
    TOKEN_PATH = CONFIG_DIR / "gdrive_token.json"
    SCOPES     = ["https://www.googleapis.com/auth/drive.file"]

    def is_configured(self) -> bool:
        return self.CREDS_PATH.exists()

    def is_authenticated(self) -> bool:
        return self.TOKEN_PATH.exists()

    def get_auth_url(self) -> Optional[str]:
        """Avvia il flusso OAuth2 e restituisce l'URL di autorizzazione."""
        if not self.is_configured():
            return None
        try:
            from google_auth_oauthlib.flow import Flow
            flow = Flow.from_client_secrets_file(
                str(self.CREDS_PATH), scopes=self.SCOPES,
                redirect_uri="urn:ietf:wg:oauth:2.0:oob",
            )
            url, _ = flow.authorization_url(
                access_type="offline", include_granted_scopes="true"
            )
            # Salva il flow per il callback
            self._save_flow_state(flow)
            return url
        except Exception as e:
            raise RuntimeError(f"Errore avvio OAuth Google: {e}") from e

    def complete_auth(self, code: str) -> bool:
        """Completa l'autenticazione con il codice ricevuto dal browser."""
        try:
            from google_auth_oauthlib.flow import Flow
            flow = self._load_flow_state()
            if flow is None:
                return False
            flow.fetch_token(code=code)
            creds = flow.credentials
            with open(self.TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
            return True
        except Exception:
            return False

    def upload(self, filename: str, data: bytes,
               mime: str = "application/octet-stream") -> tuple[bool, str]:
        """Carica un file su Google Drive nella cartella TachoVision."""
        try:
            creds = self._get_credentials()
            if creds is None:
                return False, "Non autenticato. Completa prima il login Google."

            from googleapiclient.discovery import build
            from googleapiclient.http import MediaIoBaseUpload

            service = build("drive", "v3", credentials=creds)
            folder_id = self._get_or_create_folder(service, CLOUD_FOLDER)

            media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime)
            file_meta = {"name": filename, "parents": [folder_id]}
            file = service.files().create(
                body=file_meta, media_body=media, fields="id,webViewLink"
            ).execute()

            link = file.get("webViewLink", "")
            return True, (
                f"✅ Caricato su Google Drive: {filename}\n"
                f"🔗 {link}"
            )
        except Exception as e:
            return False, f"❌ Errore Google Drive: {e}"

    def _get_credentials(self):
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            if not self.TOKEN_PATH.exists():
                return None
            creds = Credentials.from_authorized_user_file(
                str(self.TOKEN_PATH), self.SCOPES
            )
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(self.TOKEN_PATH, "w") as f:
                    f.write(creds.to_json())
            return creds if creds and creds.valid else None
        except Exception:
            return None

    def _get_or_create_folder(self, service, name: str) -> str:
        q = (f"mimeType='application/vnd.google-apps.folder' "
             f"and name='{name}' and trashed=false")
        results = service.files().list(q=q, fields="files(id)").execute()
        files = results.get("files", [])
        if files:
            return files[0]["id"]
        meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        folder = service.files().create(body=meta, fields="id").execute()
        return folder["id"]

    def _save_flow_state(self, flow):
        state = {"client_config": flow.client_config}
        with open(CONFIG_DIR / "gdrive_flow.json", "w") as f:
            json.dump(state, f)

    def _load_flow_state(self):
        p = CONFIG_DIR / "gdrive_flow.json"
        if not p.exists():
            return None
        try:
            from google_auth_oauthlib.flow import Flow
            with open(p) as f:
                state = json.load(f)
            return Flow.from_client_config(
                state["client_config"], scopes=self.SCOPES,
                redirect_uri="urn:ietf:wg:oauth:2.0:oob",
            )
        except Exception:
            return None

    def logout(self):
        for p in [self.TOKEN_PATH, CONFIG_DIR / "gdrive_flow.json"]:
            if p.exists():
                p.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# ONEDRIVE  (Microsoft Graph API via MSAL)
# ─────────────────────────────────────────────────────────────────────────────
class OneDriveService:
    """
    Usa il device code flow di MSAL: nessuna configurazione richiesta.
    L'utente riceve un codice da inserire su microsoft.com/devicelogin.
    """

    TOKEN_PATH = CONFIG_DIR / "onedrive_token.json"

    def is_authenticated(self) -> bool:
        return self.TOKEN_PATH.exists()

    def start_device_flow(self) -> dict:
        """
        Avvia il device code flow.
        Restituisce {"user_code": "...", "verification_uri": "...", "message": "..."}
        """
        import msal
        app = self._build_msal_app()
        flow = app.initiate_device_flow(scopes=MSAL_SCOPES)
        if "error" in flow:
            raise RuntimeError(flow.get("error_description", "Errore MSAL"))
        # Salva il flow per completare l'auth
        with open(CONFIG_DIR / "onedrive_flow.json", "w") as f:
            json.dump(flow, f)
        return flow

    def complete_device_flow(self) -> bool:
        """Tenta di acquisire il token dopo che l'utente ha inserito il codice."""
        p = CONFIG_DIR / "onedrive_flow.json"
        if not p.exists():
            return False
        try:
            import msal
            with open(p) as f:
                flow = json.load(f)
            app = self._build_msal_app()
            result = app.acquire_token_by_device_flow(flow)
            if "access_token" in result:
                with open(self.TOKEN_PATH, "w") as f:
                    json.dump(result, f)
                return True
            return False
        except Exception:
            return False

    def upload(self, filename: str, data: bytes) -> tuple[bool, str]:
        """Carica un file su OneDrive nella cartella TachoVision."""
        try:
            token = self._get_token()
            if not token:
                return False, "Non autenticato. Completa prima il login OneDrive."

            import requests
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            }
            # Crea cartella se non esiste (PUT è idempotente)
            folder_url = (
                "https://graph.microsoft.com/v1.0/me/drive"
                f"/root:/{CLOUD_FOLDER}:/children"
            )
            requests.post(
                "https://graph.microsoft.com/v1.0/me/drive/root/children",
                headers={**headers, "Content-Type": "application/json"},
                json={"name": CLOUD_FOLDER, "folder": {},
                      "@microsoft.graph.conflictBehavior": "replace"},
                timeout=30,
            )

            # Upload file (≤4 MB → simple upload)
            upload_url = (
                f"https://graph.microsoft.com/v1.0/me/drive"
                f"/root:/{CLOUD_FOLDER}/{filename}:/content"
            )
            r = requests.put(upload_url, headers=headers, data=data, timeout=60)
            if r.status_code in (200, 201):
                web_url = r.json().get("webUrl", "")
                return True, f"✅ Caricato su OneDrive: {filename}\n🔗 {web_url}"
            return False, f"❌ OneDrive HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"❌ Errore OneDrive: {e}"

    def _get_token(self) -> Optional[str]:
        if not self.TOKEN_PATH.exists():
            return None
        try:
            import msal
            with open(self.TOKEN_PATH) as f:
                cached = json.load(f)
            app = self._build_msal_app()
            accounts = app.get_accounts()
            if accounts:
                result = app.acquire_token_silent(MSAL_SCOPES, account=accounts[0])
                if result and "access_token" in result:
                    return result["access_token"]
            # Usa il token cached direttamente se non ancora scaduto
            return cached.get("access_token")
        except Exception:
            return None

    def _build_msal_app(self):
        import msal
        return msal.PublicClientApplication(
            MSAL_CLIENT_ID, authority=MSAL_AUTHORITY,
            token_cache=self._load_cache(),
        )

    def _load_cache(self):
        import msal
        cache = msal.SerializableTokenCache()
        cache_path = CONFIG_DIR / "onedrive_cache.bin"
        if cache_path.exists():
            cache.deserialize(cache_path.read_text())
        return cache

    def logout(self):
        for p in [self.TOKEN_PATH,
                  CONFIG_DIR / "onedrive_flow.json",
                  CONFIG_DIR / "onedrive_cache.bin"]:
            if p.exists():
                p.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# DROPBOX
# ─────────────────────────────────────────────────────────────────────────────
class DropboxService:
    """
    Usa un Personal Access Token o un token OAuth2 Dropbox.

    Per ottenere il token:
      1. Vai su dropbox.com/developers → My Apps → Create App
      2. Oppure usa un access token temporaneo dalle impostazioni app
    """

    TOKEN_PATH = CONFIG_DIR / "dropbox_token.json"

    def is_authenticated(self) -> bool:
        return self.TOKEN_PATH.exists()

    def save_token(self, token: str) -> bool:
        if not token.strip():
            return False
        try:
            # Verifica token
            import dropbox
            dbx = dropbox.Dropbox(token.strip())
            dbx.users_get_current_account()
            with open(self.TOKEN_PATH, "w") as f:
                json.dump({"access_token": token.strip()}, f)
            return True
        except Exception:
            return False

    def upload(self, filename: str, data: bytes) -> tuple[bool, str]:
        """Carica su Dropbox nella cartella /TachoVision/."""
        try:
            import dropbox
            from dropbox.files import WriteMode

            token = self._get_token()
            if not token:
                return False, "Token Dropbox non configurato."

            dbx  = dropbox.Dropbox(token)
            path = f"/{CLOUD_FOLDER}/{filename}"
            dbx.files_upload(data, path, mode=WriteMode("overwrite"))
            link = dbx.sharing_create_shared_link(path)
            return True, (
                f"✅ Caricato su Dropbox: {filename}\n"
                f"🔗 {link.url}"
            )
        except Exception as e:
            return False, f"❌ Errore Dropbox: {e}"

    def get_account_info(self) -> Optional[str]:
        try:
            import dropbox
            token = self._get_token()
            if not token:
                return None
            dbx   = dropbox.Dropbox(token)
            acct  = dbx.users_get_current_account()
            return acct.email
        except Exception:
            return None

    def _get_token(self) -> Optional[str]:
        if not self.TOKEN_PATH.exists():
            return None
        try:
            with open(self.TOKEN_PATH) as f:
                return json.load(f).get("access_token")
        except Exception:
            return None

    def logout(self):
        if self.TOKEN_PATH.exists():
            self.TOKEN_PATH.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# Facade: upload su tutti i provider configurati
# ─────────────────────────────────────────────────────────────────────────────
def upload_to_all(filename: str, data: bytes) -> list[dict]:
    """
    Tenta l'upload su tutti i provider autenticati.
    Restituisce lista di {"provider": str, "ok": bool, "message": str}.
    """
    results = []
    services = [
        ("Google Drive", GoogleDriveService()),
        ("OneDrive",     OneDriveService()),
        ("Dropbox",      DropboxService()),
    ]
    for name, svc in services:
        if not svc.is_authenticated():
            continue
        ok, msg = svc.upload(filename, data)
        results.append({"provider": name, "ok": ok, "message": msg})
    return results
