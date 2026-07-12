# src/ytm_taste/ytmusic_client.py
from ytmusicapi import YTMusic
from ytmusicapi.auth.oauth import OAuthCredentials


def get_client_from_oauth(oauth_token: dict, credentials: OAuthCredentials) -> YTMusic:
    return YTMusic(auth=oauth_token, oauth_credentials=credentials)


def fetch_history(client: YTMusic) -> list[dict]:
    return client.get_history()


def get_channel_handle(client: YTMusic) -> str | None:
    return client.get_account_info().get("channelHandle")
