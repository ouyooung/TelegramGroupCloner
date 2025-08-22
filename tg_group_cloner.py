import os
import asyncio
import random

from typing import Dict
from collections import defaultdict
from typing import Optional
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import InputPhoto, InputChannel
from telethon.tl.custom.message import Message
from utils.log import logger
from utils.file_ext import Config, load_config, init_files
from modules import telegram_client

clients_pool: Dict[TelegramClient, Optional[int]] = {}
client_locks: Dict[TelegramClient, asyncio.Lock] = {}
sender_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
message_id_mapping: Dict[int, int] = {}
cloned_users: set[int] = set()


async def login_new_account() -> None:
    phone = input("输入手机号: ")
    client = TelegramClient(f"sessions/{phone}", Config.API_ID, Config.API_HASH, proxy=Config.PROXY)
    await client.connect()

    if not await client.is_user_authorized():
        y = await client.send_code_request(phone)
        code = input("输入验证码: ")
        try:
            await client.sign_in(phone, code, phone_code_hash=y.phone_code_hash)
        except SessionPasswordNeededError:
            password = input("请输入2FA 密码: ")
            await client.sign_in(password=password)
    await client.disconnect()
    logger.info(f"克隆账号添加成功: {phone}")


async def load_existing_sessions() -> None:
    for filename in os.listdir("sessions"):
        if filename.endswith(".session"):
            session_name = filename.replace(".session", "")

            client = await telegram_client.login_client(session_name)

            if client:
                clients_pool[client] = None
                client_locks[client] = asyncio.Lock()


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
            logger.info(f"ID在黑名单中: {sender_id}")
            return

        if any(keyword in event.message.text for keyword in Config.KEYWORDS):
            logger.info(f"消息包含黑名单关键词: {sender_id}")
            return

        if any(name in full_name for name in Config.NAMES):
            logger.info(f"昵称包含黑名单名称: {sender_id}")
            return

        for client, cloned_user in clients_pool.items():
            if cloned_user == sender_id:
                # 已分配过的 client
                lock = client_locks[client]
                async with lock:
                    await asyncio.sleep(random.uniform(0.5, 3.5))
                    try:
                        me = await client.get_me()
                        await forward_message_as(
                            client, event, monitor_client)
                        logger.info(f"[{me.phone}] 转发新消息: {sender_id}")
                    except Exception as e:
                        if "FROZEN_METHOD_INVALID" in str(e):
                            await cleanup_frozen_client(client, sender_id)
                        logger.warning(f"转发失败（已克隆用户）: {e}")
                return
            elif cloned_user is None:
                # 未分配过的 client
                lock = client_locks[client]
                async with lock:
                    try:
                        await monitor_client.get_input_entity(sender_id)
                        me = await client.get_me()
                        phone = me.phone

                        logger.info(f"[{phone}] 正在克隆新用户: {sender_id}")

                        clients_pool[client] = sender_id
                        cloned_users.add(sender_id)

                        await forward_message_as(client, event, monitor_client)

                        await telegram_client.set_profile(client, monitor_client, sender, phone)

                        logger.info(f"[{phone}] 完成新用户克隆: {sender_id}")
                    except ValueError:
                        logger.warning(f"用户无法解析: {sender_id}")
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
        await client_locks.pop(client, None)

        if sender_id:
            cloned_users.discard(sender_id)

    except Exception as e:
        logger.warning(f"清理被冻结账号失败: {e}")


async def start_monitor() -> None:
    session_file = "monitor"
    monitor_client = TelegramClient(session_file, Config.API_ID, Config.API_HASH, proxy=Config.PROXY)

    await monitor_client.connect()

    if not await monitor_client.is_user_authorized():
        phone = input("请输入监听账号手机号: ")
        y = await monitor_client.send_code_request(phone)
        code = input("输入验证码: ")
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


async def run(choice):
    await load_existing_sessions()
    if choice == "1":
        await login_new_account()
    elif choice == "2":
        await start_monitor()
    elif choice == "3":
        for client in clients_pool.keys():
            await delete_profile_photos(client)
    elif choice == "4":
        for client in clients_pool.keys():
            await check_and_join_target(client)


async def main():
    os.system("title TelegramGroupCloner")

    init_files()
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

        choice = input("请选择操作: ").strip()
        if choice:
            await run(choice)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
