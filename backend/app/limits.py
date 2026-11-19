from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import get_settings

limiter = Limiter(key_func=get_remote_address, default_limits=[get_settings().rate_limit_default],
                  storage_uri=get_settings().redis_url or "memory://")
