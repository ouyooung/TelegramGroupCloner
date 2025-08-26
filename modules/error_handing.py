from typing import Dict, Type
from telethon.errors import ChatWriteForbiddenError, ChatRestrictedError

error_map: Dict[Type[Exception], str] = {
    ChatWriteForbiddenError: "目标为频道或账号受到限制",
    ChatRestrictedError: "聊天受到限制，没有发送消息的权限"
}


async def error_handle(error: Exception) -> str:
    error_type = type(error)

    if error_type in error_map:
        return error_map[error_type]
    else:
        return f"未处理的错误类型: {error_type.__name__} - {str(error)}"
