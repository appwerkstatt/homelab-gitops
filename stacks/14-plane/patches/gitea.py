# Copyright (c) 2023-present Plane Software, Inc. and contributors
# Copyright (c) 2026 appwerkstatt (homelab-gitops), changes below
# SPDX-License-Identifier: AGPL-3.0-only
#
# Homelab patch for Plane Community Edition (makeplane/plane-backend).
# Replaces plane/authentication/provider/oauth/gitea.py via a read-only bind mount
# (stacks/14-plane/compose.yaml). The "Gitea" login now speaks plain OpenID Connect
# with Keycloak instead of the Gitea API:
#
#   God Mode -> Authentication -> Gitea
#     Host          = Keycloak realm issuer, e.g. https://auth.appsfab.org/realms/AppsFab
#     Client ID     = plane
#     Client secret = secret of the Keycloak client "plane"
#
# Only the endpoints and the user mapping differ from upstream. Account linking, sign-up
# rules (ENABLE_SIGNUP / workspace invites) and sessions stay Plane's own code.
# License checks are not touched. Upstream source of the replaced file:
# https://github.com/makeplane/plane/blob/v1.5.1/apps/api/plane/authentication/provider/oauth/gitea.py
# stacks/14-plane/patches/upstream.sha256 pins the upstream files this patch relies on;
# CI fails when a Plane update changes them, so the patch gets checked before the update merges.

import os
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

import pytz

# Module imports
from plane.authentication.adapter.oauth import OauthAdapter
from plane.license.utils.instance_value import get_configuration_value
from plane.authentication.adapter.error import (
    AUTHENTICATION_ERROR_CODES,
    AuthenticationException,
)


class GiteaOAuthProvider(OauthAdapter):
    # Provider name stays "gitea": URLs (/auth/gitea/...), God Mode form and the
    # login button in the web app all hang on it.
    provider = "gitea"
    scope = "openid email profile"

    def __init__(self, request, code=None, state=None, callback=None):
        (GITEA_CLIENT_ID, GITEA_CLIENT_SECRET, GITEA_HOST, IS_GITEA_ENABLED) = get_configuration_value(
            [
                {
                    "key": "GITEA_CLIENT_ID",
                    "default": os.environ.get("GITEA_CLIENT_ID"),
                },
                {
                    "key": "GITEA_CLIENT_SECRET",
                    "default": os.environ.get("GITEA_CLIENT_SECRET"),
                },
                {
                    "key": "GITEA_HOST",
                    "default": os.environ.get("GITEA_HOST"),
                },
                {
                    "key": "IS_GITEA_ENABLED",
                    "default": os.environ.get("IS_GITEA_ENABLED", "0"),
                },
            ]
        )

        # v1.5.1: a provider switched off in God Mode must not keep working (upstream fix)
        if not (IS_GITEA_ENABLED == "1" and GITEA_CLIENT_ID and GITEA_CLIENT_SECRET and GITEA_HOST):
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["GITEA_NOT_CONFIGURED"],
                error_message="GITEA_NOT_CONFIGURED",
            )

        parsed = urlparse(GITEA_HOST)
        if not parsed.scheme or parsed.scheme not in ("https", "http"):
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["GITEA_NOT_CONFIGURED"],
                error_message="GITEA_NOT_CONFIGURED",
            )
        # Keycloak realm issuer, e.g. https://auth.appsfab.org/realms/AppsFab
        issuer = GITEA_HOST.rstrip("/")
        oidc_base = f"{issuer}/protocol/openid-connect"

        self.token_url = f"{oidc_base}/token"
        self.userinfo_url = f"{oidc_base}/userinfo"

        client_id = GITEA_CLIENT_ID
        client_secret = GITEA_CLIENT_SECRET

        redirect_uri = f"{'https' if request.is_secure() else 'http'}://{request.get_host()}/auth/gitea/callback/"
        url_params = {
            "client_id": client_id,
            "scope": self.scope,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        auth_url = f"{oidc_base}/auth?{urlencode(url_params)}"

        super().__init__(
            request,
            self.provider,
            client_id,
            self.scope,
            redirect_uri,
            auth_url,
            self.token_url,
            self.userinfo_url,
            client_secret,
            code,
            callback=callback,
        )

    def set_token_data(self):
        data = {
            "code": self.code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        headers = {"Accept": "application/json"}
        token_response = self.get_user_token(data=data, headers=headers)
        now = datetime.now(tz=pytz.utc)
        super().set_token_data(
            {
                "access_token": token_response.get("access_token"),
                "refresh_token": token_response.get("refresh_token", None),
                "access_token_expired_at": (
                    now + timedelta(seconds=token_response.get("expires_in"))
                    if token_response.get("expires_in")
                    else None
                ),
                # Keycloak: refresh_expires_in (seconds), 0 = offline token without expiry
                "refresh_token_expired_at": (
                    now + timedelta(seconds=token_response.get("refresh_expires_in"))
                    if token_response.get("refresh_expires_in")
                    else None
                ),
                "id_token": token_response.get("id_token", ""),
            }
        )

    def set_user_data(self):
        user_info_response = self.get_user_response()

        email = (user_info_response.get("email") or "").strip().lower()
        # Plane links logins to existing accounts by email. Only accept addresses Keycloak
        # marks as verified, otherwise a user could change their email in the account
        # console and take over someone else's Plane account (same idea as upstream's
        # GHSA-7j95-vh8g-f365 fix for Gitea).
        if not email or user_info_response.get("email_verified") is not True:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OAUTH_PROVIDER_UNVERIFIED_EMAIL"],
                error_message="OAUTH_PROVIDER_UNVERIFIED_EMAIL",
            )

        sub = user_info_response.get("sub")
        if not sub:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["GITEA_OAUTH_PROVIDER_ERROR"],
                error_message="GITEA_OAUTH_PROVIDER_ERROR",
            )

        super().set_user_data(
            {
                "email": email,
                "user": {
                    "provider_id": str(sub),
                    "email": email,
                    "avatar": user_info_response.get("picture", ""),
                    "first_name": user_info_response.get("given_name")
                    or user_info_response.get("name")
                    or user_info_response.get("preferred_username", ""),
                    "last_name": user_info_response.get("family_name", ""),
                    "is_password_autoset": True,
                },
            }
        )
