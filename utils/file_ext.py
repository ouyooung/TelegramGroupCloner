import configparser
import os

from typing import Union
from telethon.tl.types import InputChannel, PeerChat
from utils.log import logger


class Config:
    PROXY = None
    SOURCE_GROUPS = []
    TARGET_GROUP: Union[PeerChat, InputChannel]
    USER_IDS = set()
    KEYWORDS = set()
    NAMES = set()
    REPLACEMENTS = {}
    API_ID = None
    API_HASH = None


def load_config() -> None:
    config_path = "setting/config.ini"
    default_content = """[telegram]
api_id = 9597683
api_hash = 9981e2f10aeada4452a9538921132099
source_group = ouyoung
target_group = ouyoung

[proxy]
is_enabled = true
host = 127.0.0.1
port = 7890
type = socks5

[blacklist]
user_ids = 123, 12345
keywords = 广告, 出售
names = 定制, 机器人

[replacements]
a = b
你好 = 我好
"""

    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(default_content)
            logger.info(f"已初始化配置文件: {config_path}")

    config = configparser.ConfigParser()
    try:
        config.read(config_path, encoding="utf-8-sig")

        Config.API_HASH = config.get("telegram", "api_hash")
        Config.API_ID = config.getint("telegram", "api_id")

        raw_source_gps = config.get("telegram", "source_group")
        Config.SOURCE_GROUPS = [source_gp for source_gp in raw_source_gps.split(",") if raw_source_gps.strip()]
        Config.TARGET_GROUP = config.get("telegram", "target_group")

        if config.getboolean("proxy", "is_enabled"):
            host = config.get("proxy", "host")
            port = config.getint("proxy", "port")
            proxy_type = config.get("proxy", "type")
            Config.PROXY = (proxy_type, host, port)

        user_dis = config.get("blacklist", "user_ids", fallback="")
        keywords = config.get("blacklist", "keywords", fallback="")
        names = config.get("blacklist", "names", fallback="")
        Config.USER_IDS.update(int(uid) for uid in user_dis.split(",") if uid.strip().isdigit())
        Config.KEYWORDS.update(keyword for keyword in keywords.split(",") if keyword.strip())
        Config.NAMES.update(name for name in names.split(",") if name.strip())

        if config.has_section("replacements"):
            Config.REPLACEMENTS.update(dict(config.items("replacements")))

        logger.info(f"成功加载配置文件: {config_path}")
    except Exception as e:
        logger.warning(f"配置加载失败: {e}")


def init_files():
    os.makedirs("setting", exist_ok=True)
    os.makedirs("sessions", exist_ok=True)
