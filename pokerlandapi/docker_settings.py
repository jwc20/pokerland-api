from pokerlandapi.settings import *

DATABASES["default"]["HOST"] = "db"
DATABASES["default"]["PORT"] = 5432
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]
