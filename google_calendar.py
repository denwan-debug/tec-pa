"""
Integrasi Google Calendar untuk TEC Portal.

Fitur:
- OAuth 2.0 (Authorization Code flow) supaya orang tua bisa menghubungkan
  akun Google Calendar pribadi mereka.
- Sinkronisasi 1 arah: sesi kelas anak (dari tabel sesi_kelas, lewat query
  yang sama dengan halaman Jadwal Belajar) -> event di Google Calendar milik
  orang tua. Sinkronisasi ulang akan meng-UPDATE event yang sudah pernah
  dibuat (bukan membuat dobel), karena kita simpan pemetaannya di tabel
  `google_calendar_events`.

SETUP YANG WAJIB DILAKUKAN DI LUAR KODE INI (lihat panduan lengkap dari Claude):
1. Buat project di https://console.cloud.google.com/
2. Aktifkan "Google Calendar API" untuk project tsb.
3. Buat OAuth Client ID (tipe "Web application"), tambahkan Authorized
   redirect URI, contoh:
     http://localhost:5000/google_calendar/oauth2callback   (development)
     https://domainkamu.com/google_calendar/oauth2callback  (production)
4. Set environment variable:
     GOOGLE_CLIENT_ID=...
     GOOGLE_CLIENT_SECRET=...
     GOOGLE_REDIRECT_URI=http://localhost:5000/google_calendar/oauth2callback
5. Install dependency:
     pip install google-auth google-auth-oauthlib google-api-python-client
6. Jalankan google_calendar_migration.sql di database.
"""
import os

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from db import get_db_connection

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.environ.get(
    'GOOGLE_REDIRECT_URI', 'http://localhost:5000/google_calendar/oauth2callback'
)


class GoogleCalendarNotConfigured(Exception):
    """Env var GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET belum diisi di server."""
    pass


class GoogleCalendarNotConnected(Exception):
    """User yang sedang login belum menghubungkan akun Google Calendar-nya."""
    pass


def _client_config():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise GoogleCalendarNotConfigured(
            'GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET belum di-set di environment variable server.'
        )
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }


def _build_auth_flow(state=None):
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


def get_authorization_url():
    """Membuat URL consent screen Google + state (disimpan di session Flask)."""
    flow = _build_auth_flow()
    auth_url, state = flow.authorization_url(
        access_type='offline',       # supaya dapat refresh_token
        include_granted_scopes='true',
        prompt='consent',            # paksa munculkan consent screen tiap kali (memastikan refresh_token selalu ada)
    )
    return auth_url, state


def exchange_code_for_credentials(state, authorization_response_url):
    """Menukar 'code' dari redirect Google menjadi access & refresh token."""
    flow = _build_auth_flow(state=state)
    flow.fetch_token(authorization_response=authorization_response_url)
    return flow.credentials


# ---------------------------------------------------------------------------
# Penyimpanan token di database (tabel google_calendar_tokens)
# ---------------------------------------------------------------------------

def save_credentials(id_users, credentials):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        expiry = credentials.expiry.strftime('%Y-%m-%d %H:%M:%S') if credentials.expiry else None
        cursor.execute("""
            INSERT INTO google_calendar_tokens
                (id_users, access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                access_token = VALUES(access_token),
                refresh_token = COALESCE(VALUES(refresh_token), refresh_token),
                token_uri = VALUES(token_uri),
                client_id = VALUES(client_id),
                client_secret = VALUES(client_secret),
                scopes = VALUES(scopes),
                expiry = VALUES(expiry)
        """, (
            id_users, credentials.token, credentials.refresh_token,
            credentials.token_uri, credentials.client_id, credentials.client_secret,
            ','.join(credentials.scopes or SCOPES), expiry,
        ))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def load_credentials(id_users):
    """Ambil & (kalau perlu) refresh token user. Return None kalau belum connect."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM google_calendar_tokens WHERE id_users = %s", (id_users,))
        row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not row:
        return None

    creds = Credentials(
        token=row['access_token'],
        refresh_token=row['refresh_token'],
        token_uri=row['token_uri'],
        client_id=row['client_id'],
        client_secret=row['client_secret'],
        scopes=row['scopes'].split(',') if row['scopes'] else SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        save_credentials(id_users, creds)

    return creds


def is_connected(id_users):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM google_calendar_tokens WHERE id_users = %s", (id_users,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def disconnect(id_users):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM google_calendar_events WHERE id_users = %s", (id_users,))
        cursor.execute("DELETE FROM google_calendar_tokens WHERE id_users = %s", (id_users,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# Sinkronisasi jadwal -> Google Calendar
# ---------------------------------------------------------------------------

def _get_synced_event_id(cursor, id_users, id_sesi):
    cursor.execute(
        "SELECT google_event_id FROM google_calendar_events WHERE id_users = %s AND id_sesi = %s",
        (id_users, id_sesi)
    )
    row = cursor.fetchone()
    return row['google_event_id'] if row else None


def _save_synced_event_id(cursor, id_users, id_sesi, google_event_id):
    cursor.execute("""
        INSERT INTO google_calendar_events (id_users, id_sesi, google_event_id)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE google_event_id = VALUES(google_event_id)
    """, (id_users, id_sesi, google_event_id))


def sync_jadwal_to_calendar(id_users, daftar_jadwal, nama_anak=None):
    """
    Push semua sesi kelas yang punya tanggal pasti (tanggal_iso terisi, dari
    tabel sesi_kelas) ke Google Calendar milik user yang sedang login.

    Jadwal 'Terjadwal Rutin' (kelas terdaftar tapi belum ada sesi_kelas
    spesifik) dilewati karena belum punya tanggal pasti untuk dibuatkan event.

    Return: dict {'created': n, 'updated': n, 'skipped': n, 'error': n}
    """
    creds = load_credentials(id_users)
    if creds is None:
        raise GoogleCalendarNotConnected()

    service = build('calendar', 'v3', credentials=creds)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    hasil = {'created': 0, 'updated': 0, 'skipped': 0, 'error': 0}

    try:
        for jadwal in daftar_jadwal:
            if not jadwal.get('tanggal_iso') or not jadwal.get('id_sesi'):
                hasil['skipped'] += 1
                continue

            tanggal = jadwal['tanggal_iso']
            start_dt = f"{tanggal}T{jadwal['jam_mulai']}:00"
            end_dt = f"{tanggal}T{jadwal['jam_selesai']}:00"

            judul = jadwal['nama_kelas']
            if nama_anak:
                judul = f"{jadwal['nama_kelas']} - {nama_anak}"

            deskripsi_parts = [f"Pengajar: {jadwal.get('nama_pengajar') or '-'}"]
            if jadwal.get('topik'):
                deskripsi_parts.append(f"Topik: {jadwal['topik']}")

            event_body = {
                'summary': judul,
                'description': '\n'.join(deskripsi_parts),
                'start': {'dateTime': start_dt, 'timeZone': 'Asia/Jakarta'},
                'end': {'dateTime': end_dt, 'timeZone': 'Asia/Jakarta'},
                'reminders': {'useDefault': True},
            }

            existing_event_id = _get_synced_event_id(cursor, id_users, jadwal['id_sesi'])

            try:
                if existing_event_id:
                    service.events().update(
                        calendarId='primary', eventId=existing_event_id, body=event_body
                    ).execute()
                    hasil['updated'] += 1
                else:
                    created = service.events().insert(
                        calendarId='primary', body=event_body
                    ).execute()
                    _save_synced_event_id(cursor, id_users, jadwal['id_sesi'], created['id'])
                    hasil['created'] += 1
            except HttpError as e:
                status_code = getattr(e, 'status_code', None) or getattr(getattr(e, 'resp', None), 'status', None)
                if existing_event_id and status_code == 404:
                    # Event lama sepertinya sudah dihapus manual dari Google Calendar -> buat baru
                    created = service.events().insert(calendarId='primary', body=event_body).execute()
                    _save_synced_event_id(cursor, id_users, jadwal['id_sesi'], created['id'])
                    hasil['created'] += 1
                else:
                    print(f"Google Calendar sync error (id_sesi={jadwal['id_sesi']}): {e}")
                    hasil['error'] += 1

        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return hasil