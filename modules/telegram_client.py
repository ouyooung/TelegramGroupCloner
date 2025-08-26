import os

from typing import Union
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.account import UpdateProfileRequest, UpdateEmojiStatusRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.tl.types import User
from utils.file_ext import Config
from utils.log import logger


async def login_client(session_name: str, sign_in: bool = False) -> Union[TelegramClient, bool]:
    logger.info(f"正在加载: {session_name}")

    client = TelegramClient(f"{session_name}", Config.API_ID, Config.API_HASH, proxy=Config.PROXY)
    await client.connect()

    if not await client.is_user_authorized():
        if not sign_in:
            logger.info(f"未授权: {session_name}")
            await client.disconnect()
            await cleanup_not_authorized_client(session_name)
            return False

        try:
            phone = input("请输入手机号: ")
            y = await client.send_code_request(phone)
            code = input("输入验证码: ")
            await client.sign_in(phone, code, phone_code_hash=y.phone_code_hash)

        except SessionPasswordNeededError:
            password = input("请输入2FA密码: ")
            await client.sign_in(password=password)

        except Exception as e:
            logger.error(f"登录发生错误: {e}")
            await client.disconnect()
            return False

        if not await client.is_user_authorized():
            logger.error(f"登录失败: {session_name}")
            await client.disconnect()
            return False

        logger.info(f"首次登录成功: {session_name}")
        return client

    else:
        logger.info(f"加载成功: {session_name}")
        return client


async def set_profile(client: TelegramClient, monitor_client: TelegramClient, sender: User, phone: str) -> None:
    sender_id = sender.id
    try:
        await client(UpdateProfileRequest(
            first_name=sender.first_name or " ",
            last_name=sender.last_name or "",
        ))
        logger.info(f"[{phone}] 设置昵称成功: {sender_id}")

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

                logger.info(f"[{phone}] 设置头像成功: {sender_id}")
            else:
                logger.warning(f"[{phone}] 头像无法下载: {sender_id}")
        else:
            logger.info(f"[{phone}] 用户未设置头像: {sender_id}")
        if sender.emoji_status:
            me = await client.get_me()
            if me.premium:
                await client(UpdateEmojiStatusRequest(sender.emoji_status))
                logger.info(f"[{phone}] 设置Emoji状态成功: {sender_id}，如果是礼物状态则无法设置")
        else:
            logger.info(f"[{phone}] 用户未设置状态: {sender_id}")

    except Exception as e:
        logger.error(f"设置资料出现错误: {e}")


async def cleanup_not_authorized_client(session_name):
    try:
        os.remove(f"sessions/{session_name}.session")
        logger.info(f"清理未授权session成功 {session_name}")
    except PermissionError:
        logger.warning(f"清理未授权session失败 {session_name}，文件正在使用中")
