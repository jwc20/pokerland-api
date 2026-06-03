from django.contrib.auth import get_user_model


def get_user_from_client_token_hash(client_token_hash: str):
    normalized = client_token_hash.lower()
    return get_user_model().objects.get(client_token_hash=normalized)
