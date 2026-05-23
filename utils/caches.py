from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache


@dataclass()
class CacheConfig:
    prefix: str
    ttl: int
    cache_key_info: OrderedDict

    def with_ttl(self, new_ttl: int) -> "CacheConfig":
        return CacheConfig(
            prefix=self.prefix, ttl=new_ttl, cache_key_info=self.cache_key_info
        )

    def with_cache_keys(self, **keys) -> "CacheConfig":
        new_cache_key_info = OrderedDict(self.cache_key_info)
        for key, value in keys.items():
            if key in new_cache_key_info:
                new_cache_key_info[key] = value
        return CacheConfig(
            prefix=self.prefix, ttl=self.ttl, cache_key_info=new_cache_key_info
        )


# 기본 TTL 설정
CONTENT_LIST = CacheConfig(
    prefix="content_list",
    ttl=60 * 1,  # 1분
    cache_key_info=OrderedDict([("channel_id", None), ("page", None)]),
)
COMMUNITY_POST_LIST = CacheConfig(
    prefix="community_post_list",
    ttl=60 * 1,  # 1분
    cache_key_info=OrderedDict([("channel_id", None), ("page", None)]),
)


class CacheHandler:
    def __init__(self, cache_config: CacheConfig):
        self.cache_config = cache_config

    def get_cache_key(self) -> str:
        cache_prefix = self.cache_config.prefix
        result = f"{cache_prefix}"
        for k, v in self.cache_config.cache_key_info.items():
            result += f":{k}:{v}"
        return result

    def get_cached_data(self) -> Any:
        cache_key = self.get_cache_key()
        return cache.get(cache_key)

    def set_cached_data(
        self,
        data: Any,
    ) -> None:
        cache_key = self.get_cache_key()
        cache.set(cache_key, data, timeout=self.cache_config.ttl)

    def delete_cached_data(self) -> None:
        cache_key = self.get_cache_key()
        cache.delete(cache_key)
