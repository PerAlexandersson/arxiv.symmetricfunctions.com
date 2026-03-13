"""
auth.py - User authentication via ORCID OAuth

Routes:
    GET  /login                  → login page (ORCID button)
    GET  /login/orcid            → start ORCID OAuth flow
    GET  /login/orcid/callback   → handle redirect, upsert user, set session
    GET  /logout                 → clear session
"""

import os
import requests as http_requests
from flask import (Blueprint, render_template, redirect, url_for,
                   session, request, flash, current_app)
from authlib.integrations.flask_client import OAuth
from config import ORCID_CLIENT_ID, ORCID_CLIENT_SECRET, ADMIN_ORCID
from db import get_db_connection

DEV_ORCID_ID = os.getenv('DEV_ORCID_ID', '')

auth = Blueprint('auth', __name__)

# OAuth object — bound to the Flask app via init_oauth(app)
oauth = OAuth()


def init_oauth(app):
    """Call this once after creating the Flask app."""
    oauth.init_app(app)
    if ORCID_CLIENT_ID and ORCID_CLIENT_SECRET:
        oauth.register(
            name='orcid',
            client_id=ORCID_CLIENT_ID,
            client_secret=ORCID_CLIENT_SECRET,
            server_metadata_url='https://orcid.org/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid',
                'token_endpoint_auth_method': 'client_secret_post',
            },
        )



def _fetch_orcid_name(orcid_id):
    """Fetch display name from ORCID public API. Returns orcid_id on failure."""
    try:
        resp = http_requests.get(
            f"https://pub.orcid.org/v3.0/{orcid_id}/person",
            headers={'Accept': 'application/json'},
            timeout=5
        )
        if resp.ok:
            data = resp.json()
            name_obj = data.get('name') or {}
            given  = (name_obj.get('given-names')  or {}).get('value', '')
            family = (name_obj.get('family-name')   or {}).get('value', '')
            full   = ' '.join(filter(None, [given, family]))
            return full or orcid_id
    except Exception:
        pass
    return orcid_id


def _set_session(user_id, name, orcid_id):
    session.permanent = True   # persist across browser restarts
    session['user_id']   = user_id
    session['user_name'] = name
    session['orcid_id']  = orcid_id
    if ADMIN_ORCID and orcid_id == ADMIN_ORCID:
        session['admin_logged_in'] = True


def _upsert_user(provider, provider_id, display_name):
    """Insert or update a user row and return the internal user id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO users (provider, provider_id, display_name)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE display_name = VALUES(display_name)""",
            (provider, provider_id, display_name)
        )
        conn.commit()
        cursor.execute(
            "SELECT id FROM users WHERE provider=%s AND provider_id=%s",
            (provider, provider_id)
        )
        row = cursor.fetchone()
        return row['id']
    finally:
        cursor.close()


# ── Routes ────────────────────────────────────────────────────────────────────

@auth.route('/login')
def login():
    if session.get('user_id'):
        return redirect(url_for('index'))
    orcid_enabled = bool(ORCID_CLIENT_ID and ORCID_CLIENT_SECRET)
    return render_template('login.html', orcid_enabled=orcid_enabled)


@auth.route('/login/orcid')
def login_orcid():
    if not (ORCID_CLIENT_ID and ORCID_CLIENT_SECRET):
        flash('ORCID login is not configured on this server.')
        return redirect(url_for('auth.login'))
    redirect_uri = url_for('auth.orcid_callback', _external=True)
    return oauth.orcid.authorize_redirect(redirect_uri)


@auth.route('/login/orcid/callback')
def orcid_callback():
    try:
        token = oauth.orcid.authorize_access_token()
    except Exception:
        flash('Login failed. Please try again.')
        return redirect(url_for('auth.login'))

    userinfo = token.get('userinfo') or {}
    orcid_id = userinfo.get('sub', '')
    if not orcid_id:
        flash('Could not retrieve ORCID iD. Please try again.')
        return redirect(url_for('auth.login'))

    # Build display name: prefer full name from id_token, else ORCID API, else iD
    name = (userinfo.get('name') or
            ' '.join(filter(None, [userinfo.get('given_name'), userinfo.get('family_name')])))
    if not name:
        name = _fetch_orcid_name(orcid_id)

    user_id = _upsert_user('orcid', orcid_id, name)
    _set_session(user_id, name, orcid_id)

    next_url = session.pop('login_next', None)
    return redirect(next_url or url_for('index'))


@auth.route('/dev-login')
def dev_login():
    """Dev-only shortcut: log in as DEV_ORCID_ID without OAuth.
    Only works when DEV_ORCID_ID is set in .env (never set this in production).
    """
    if not DEV_ORCID_ID:
        return redirect(url_for('admin.login'))
    name = _fetch_orcid_name(DEV_ORCID_ID)
    user_id = _upsert_user('orcid', DEV_ORCID_ID, name)
    _set_session(user_id, name, DEV_ORCID_ID)
    return redirect(url_for('index'))


@auth.route('/logout')
def logout():
    session.pop('user_id',        None)
    session.pop('user_name',      None)
    session.pop('orcid_id',       None)
    session.pop('admin_logged_in', None)
    return redirect(url_for('index'))
