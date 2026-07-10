import os

from ytmusicapi import YTMusic


def get_client(auth_file_path: str) -> YTMusic:
    if not os.path.exists(auth_file_path):
        raise RuntimeError(
            f"Auth file not found at '{auth_file_path}'. Run "
            f"'ytmusicapi browser --file {auth_file_path}' first to set up authentication."
        )
    return YTMusic(auth_file_path)


def fetch_history(client: YTMusic) -> list[dict]:
    return client.get_history()
