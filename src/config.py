import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class TAConfig:
    url: str
    user: str
    password: str


class Settings:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    SESSION_ROOT = os.path.abspath(os.getenv("USER_DATA_DIR", "./ta_session"))
    TA_CREDENTIALS = {
        "china": TAConfig(os.getenv("TA_URL_CN", ""), os.getenv("TA_USER_CN", ""), os.getenv("TA_PASS_CN", "")),
        "global": TAConfig(os.getenv("TA_URL_GLOBAL", ""), os.getenv("TA_USER_GLOBAL", ""), os.getenv("TA_PASS_GLOBAL", "")),
    }

    def region_for_sql_url(self, sql_url: str) -> str:
        """Choose an account from the URL in the SQL header, never from CLI defaults."""
        host = (urlparse(sql_url).hostname or "").lower()
        configured_hosts = {
            region: (urlparse(config.url).hostname or "").lower()
            for region, config in self.TA_CREDENTIALS.items()
        }
        if host and host == configured_hosts["china"]:
            return "china"
        if host and host == configured_hosts["global"]:
            return "global"

        china_hosts = {"ss-web.5xgames.com"}
        china_hosts.update(h.strip().lower() for h in os.getenv("TA_CN_HOSTS", "").split(",") if h.strip())
        global_hosts = {h.strip().lower() for h in os.getenv("TA_GLOBAL_HOSTS", "").split(",") if h.strip()}
        if host in china_hosts:
            return "china"
        if host in global_hosts:
            return "global"
        raise ValueError(
            f"Cannot determine China or international ThinkingData from URL host: {host or sql_url}. "
            "Set TA_CN_HOSTS or TA_GLOBAL_HOSTS in .env."
        )

    def session_dir_for(self, region: str) -> str:
        return f"{self.SESSION_ROOT}_{region}"


settings = Settings()
