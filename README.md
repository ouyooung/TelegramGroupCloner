# Telegram群组克隆工具 使用说明

## 项目概述
最新发布版下载：https://github.com/ouyooung/TelegramGroupCloner/releases/latest

1. **账号登录与管理**：
    - 支持通过手机号新增账号
    - 支持加载现有账号 session

2. **群组消息克隆**：
    - 监听源群组的消息，并将消息克隆到目标群组
    - 支持在新账号中设置目标用户的昵称与头像
    - 支持设置消息文本替换

3. **代理支持**：
    - 支持通过 SOCKS5 代理连接 Telegram

4. **黑名单支持**：
    - 支持对某些用户进行黑名单管理，跳过这些用户的消息克隆

## 环境要求

1. Python 3.8 或更高版本
2. 安装依赖库：
    ```bash
    pip install requirements.txt
    ```

## 配置文件

项目的配置文件 `setting/config.ini` 包含以下内容：

```ini
[telegram]
api_id = 9597683  # Telegram API ID
api_hash = 9981e2f10aeada4452a9538921132099  # Telegram API Hash
source_group = ouyoung  # 源群组名称
target_group = ouyoung  # 目标群组名称

[proxy]
is_enabled = true # 是否启用代理
host = 127.0.0.1  # SOCKS5 代理服务器地址
port = 7890  # SOCKS5 代理服务器端口
type = socks5  # 代理类型（socks5）

[blacklist]
user_ids = 123,1234  # 黑名单用户 ID 列表
keywords = 开课, @, 项目  # 黑名单关键词列表

[replacements]
a = b  # 字符串替换规则
你好 = 我好  # 字符串替换规则
```

## 配置说明：

proxy：代理配置，支持 SOCKS5 代理，host 和 port 分别为代理服务器的地址和端口。

blacklist：黑名单配置，指定不希望克隆消息的用户ID或关键词，多个用逗号分隔。

replacements：字符串替换配置，允许将指定文本替换为另一个文本。

## 其他说明
- 作者Telegram：https://t.me/ouyoung
- 交流群Telegram：https://t.me/oyDevelopersClub
