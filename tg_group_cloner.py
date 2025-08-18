import configparser
import logging
import os
import asyncio
import random

from typing import Dict
from collections import defaultdict
from typing import Optional, Union
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import InputPhoto, InputChannel, PeerChat
from telethon.tl.custom.message import Message

# 全局变量
clients_pool = {}
client_locks = {}
sender_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
message_id_mapping = {}
cloned_users = set()

logging.getLogger('telethon').setLevel(logging.WARNING)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


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


async def login_new_account() -> None:
    phone = input("输入手机号: ")
    client = TelegramClient(f"sessions/{phone}", Config.API_ID, Config.API_HASH, proxy=Config.PROXY)
    await client.connect()

    if not await client.is_user_authorized():
        y = await client.send_code_request(phone)
        code = input('输入验证码: ')
        try:
            await client.sign_in(phone, code, phone_code_hash=y.phone_code_hash)
        except SessionPasswordNeededError:
            password = input("请输入2FA 密码: ")
            await client.sign_in(password=password)

    logger.info(f"克隆账号登录成功: {phone}")


async def load_existing_sessions(choice: str) -> None:
    for filename in os.listdir('sessions'):
        if filename.endswith('.session'):
            session_name = filename.replace('.session', '')
            logger.info(f"正在加载 session: {session_name}")
            client = TelegramClient(f"sessions/{session_name}", Config.API_ID, Config.API_HASH, proxy=Config.PROXY)
            await client.connect()
            if await client.is_user_authorized():
                logger.info(f"加载成功 session: {session_name}")
                if choice == '3':
                    await delete_profile_photos(client)
                elif choice == '4':
                    await check_and_join_target(client)
                clients_pool[client] = None
                client_locks[client] = asyncio.Lock()
            else:
                logger.warning(f"未授权 session: {session_name}")
                await client.disconnect()


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

    os.makedirs("setting", exist_ok=True)
    os.makedirs('sessions', exist_ok=True)
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
        logger.error(f"配置加载失败: {e}")


async def delete_profile_photos(client: TelegramClient) -> None:
    try:
        me = await client.get_me()
        photos = await client.get_profile_photos(me.id)
        for photo in photos:
            await client(DeletePhotosRequest([
                InputPhoto(
                    id=photo.id,
                    access_hash=photo.access_hash,
                    file_reference=photo.file_reference
                )]))
        logger.info(f"[{me.phone}] 清空历史头像成功")
    except Exception as e:
        logger.error(e)


async def check_and_join_target(client: TelegramClient) -> None:
    try:
        await client(JoinChannelRequest(Config.TARGET_GROUP))
        me = await client.get_me()
        logger.info(f"[{me.phone}] 加入目标群组成功")
    except Exception as e:
        if "FROZEN_METHOD_INVALID" in str(e):
            await cleanup_frozen_client(client)
            logger.error(f"克隆账号加入目标群组失败: {e}")
        else:
            logger.info(e)


async def check_and_join_source(client: TelegramClient, group: InputChannel) -> None:
    try:
        await client(JoinChannelRequest(group))
        logger.info("监听账号加入源群组成功")
    except Exception as e:
        if "FROZEN_METHOD_INVALID" in str(e):
            await cleanup_frozen_client(client)
            logger.error(f"监听账号加入源群组失败: {e}")


async def clone_and_forward_message(event: Message, monitor_client: TelegramClient) -> None:
    sender = await event.get_sender()

    if not sender or sender.bot:
        return

    sender_id = sender.id
    full_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip()
    lock = sender_locks[sender_id]
    async with lock:
        if sender_id in Config.USER_IDS:
            logger.info(f"{sender_id} ID在黑名单中，跳过")
            return

        if any(keyword in event.message.text for keyword in Config.KEYWORDS):
            logger.info(f"{sender_id} 消息包含黑名单关键词，跳过")
            return

        if any(name in full_name for name in Config.NAMES):
            logger.info(f"{sender_id} 昵称包含黑名单名称，跳过")
            return

        # 已分配过的 client
        for client, cloned_user in clients_pool.items():
            if cloned_user == sender_id:
                lock = client_locks[client]
                async with lock:
                    await asyncio.sleep(random.uniform(1, 3.5))
                    try:
                        me = await client.get_me()
                        await forward_message_as(
                            client, event, monitor_client)
                        logger.info(f"[{me.phone}] 转发 {sender_id} 的新消息")
                    except Exception as e:
                        if "FROZEN_METHOD_INVALID" in str(e):
                            await cleanup_frozen_client(client, sender_id)
                        logger.warning(f"转发失败（已克隆用户）: {e}")
                return

        # 未分配的 client
        for client, cloned_user in clients_pool.items():
            client: TelegramClient
            if cloned_user is None:
                lock = client_locks[client]
                async with lock:  # <== 关键！锁住整个设置流程
                    try:
                        await monitor_client.get_input_entity(sender_id)
                        me = await client.get_me()

                        logger.info(f"[{me.phone}] 正在克隆新用户: {sender_id}")
                        # 再次检查是否被其他协程分配了
                        if clients_pool[client] is not None:
                            continue

                        # 设置昵称
                        await client(UpdateProfileRequest(
                            first_name=sender.first_name or " ",
                            last_name=sender.last_name or "",
                        ))
                        logger.info(f"[{me.phone}] 设置昵称成功")

                        # 设置头像
                        try:
                            photos = await monitor_client.get_profile_photos(sender, limit=1)
                            if photos:
                                profile_path = await monitor_client.download_media(photos[0])
                                if profile_path and os.path.exists(profile_path):
                                    uploaded = await client.upload_file(file=profile_path)
                                    if photos[0].video_sizes:
                                        await client(UploadProfilePhotoRequest(video=uploaded))
                                    else:
                                        await client(UploadProfilePhotoRequest(file=uploaded))
                                    os.remove(profile_path)
                                    logger.info(f"[{me.phone}] 设置头像成功")
                                else:
                                    logger.warning("头像无法下载")
                            else:
                                logger.info(f"{sender_id} 没有头像")
                        except Exception as e:
                            logger.error(f"设置头像出现错误: {e}")
                            return

                        # 发送消息
                        await forward_message_as(
                            client, event, monitor_client)

                        # 分配完成
                        clients_pool[client] = sender_id
                        cloned_users.add(sender_id)
                        logger.info(f"[{me.phone}] 完成新用户克隆: {sender_id}")
                    except ValueError:
                        logger.warning(f"用户 {sender_id} 无法解析")
                    except Exception as e:
                        if "FROZEN_METHOD_INVALID" in str(e):
                            await cleanup_frozen_client(client, sender_id)
                            logger.warning(f"克隆失败: {e}")
                    return

        logger.warning("无可用账号进行克隆")


async def forward_message_as(client: TelegramClient, event: Message, monitor_client: TelegramClient) -> None:
    message = event.message
    text = apply_replacements(message.text or "")
    target_group = Config.TARGET_GROUP

    try:
        if message.is_reply:
            try:
                reply = await event.get_reply_message()
                if not reply:
                    logger.warning("无法获取被回复消息")
                    return

                logger.info(f"找到被回复消息: {reply.id}, 来自: {reply.sender_id}")

                # 映射查找
                if reply.id in message_id_mapping:
                    reply_to_msg_id = message_id_mapping[reply.id]
                else:
                    logger.info("没有找到对应的克隆账号消息，跳过回复")
                    return

                # 发送消息（回复）
                if message.media:
                    file_path = await monitor_client.download_media(message)
                    original_attributes = message.media.document.attributes

                    # 发送文件，保持原有属性
                    sent_reply = await client.send_file(
                        target_group,
                        message.media,
                        attributes=original_attributes,
                        reply_to=reply_to_msg_id,
                        caption=text
                    )

                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                else:
                    sent_reply = await client.send_message(
                        target_group,
                        text,
                        reply_to=reply_to_msg_id
                    )

                message_id_mapping[message.id] = sent_reply.id

            except Exception as e:
                logger.warning(f"获取被回复消息失败: {e}")
        else:
            try:
                if message.media:
                    file_path = await monitor_client.download_media(message)
                    original_attributes = message.media.document.attributes
                    # 发送文件，保持原有属性
                    sent = await client.send_file(
                        target_group,
                        file_path,
                        attributes=original_attributes,
                        caption=text
                    )

                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                else:
                    sent = await client.send_message(
                        target_group,
                        text
                    )

                message_id_mapping[message.id] = sent.id

            except Exception as e:
                logger.error(f"发送当前消息失败: {e}")

    except Exception as e:
        logger.error(f"获取当前用户信息失败: {e}")


def apply_replacements(text: str) -> str:
    if not text:
        return text
    for k, v in Config.REPLACEMENTS.items():
        text = text.replace(k, v)
    return text


async def cleanup_frozen_client(client: TelegramClient, sender_id: Optional[int] = None) -> None:
    try:
        phone = (await client.get_me()).phone
        logger.info(f"[{phone}] 被冻结")

        # 断开连接
        await client.disconnect()

        # 从管理结构中移除
        clients_pool.pop(client, None)
        client_locks.pop(client, None)

        if sender_id:
            cloned_users.discard(sender_id)

    except Exception as e:
        logger.warning(f"清理被冻结账号失败: {e}")


async def start_monitor() -> None:
    session_file = 'monitor'
    monitor_client = TelegramClient(session_file, Config.API_ID, Config.API_HASH, proxy=Config.PROXY)

    await monitor_client.connect()

    if not await monitor_client.is_user_authorized():
        phone = input('请输入监听账号手机号: ')
        y = await monitor_client.send_code_request(phone)
        code = input('输入验证码: ')
        try:
            await monitor_client.sign_in(phone, code, phone_code_hash=y.phone_code_hash)
        except SessionPasswordNeededError:
            password = input("请输入2FA 密码: ")
            await monitor_client.sign_in(password=password)
    me = await monitor_client.get_me()
    logger.info(f"监听账号登录成功: {me.phone}")

    # 检查是否已经加入源群组
    try:
        for group in Config.SOURCE_GROUPS:
            await check_and_join_source(monitor_client, group)
    except Exception as er:
        if "FROZEN_METHOD_INVALID" in str(er):
            await cleanup_frozen_client(monitor_client)
        logger.error(f"监听账号加入源群组失败: {str(er)}")

    # 监听群组消息
    logger.info(f"开始监听消息")

    @monitor_client.on(events.NewMessage(chats=Config.SOURCE_GROUPS))
    async def handler(event: Message):
        try:
            await clone_and_forward_message(event, monitor_client)
        except Exception as e:
            logger.error(f"处理消息时出错: {str(e)}")

    await monitor_client.run_until_disconnected()


async def main():
    os.system("title TelegramGroupCloner v1.5.0")

    load_config()

    print("\033[31mPowered by: 欧阳\033[0m")
    print("\033[31m交流群: https://t.me/oyDevelopersClub\033[0m")
    print("\033[31m开源地址: https://github.com/ouyooung/TelegramGroupCloner\033[0m")
    print(
        "\n\033[33m请遵循当地法律法规，在合法的范围内使用本程序！任何基于本项目及本项目二次开发产生的法律纠纷责任，我们对此不承担任何责任！\033[0m")

    print("\n↓↓↓↓↓↓↓ 选择你要执行的操作 ↓↓↓↓↓↓↓")

    while True:
        print("\n1. 新增账号")
        print("2. 开始监听")
        print("3. 清空历史头像")
        print("4. 加入目标群")

        try:
            choice = input("请选择操作: ").strip()
        except KeyboardInterrupt:
            break

        if choice == '1':
            await login_new_account()
        elif choice == '2':
            await load_existing_sessions(choice)
            await start_monitor()
        elif choice == '3':
            await load_existing_sessions(choice)
            break
        elif choice == '4':
            await load_existing_sessions(choice)
            break


if __name__ == '__main__':
    asyncio.run(main())
