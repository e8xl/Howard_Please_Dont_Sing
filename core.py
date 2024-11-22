# core.py
import asyncio
import json
import os

import aiohttp
from qrcode.main import QRCode

from VoiceAPI import KookVoiceClient, VoiceClientError


# region 环境配置部分
def open_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        tmp = json.load(f)
    return tmp


config = open_file('./config/config.json')
# 指定 ffmpeg 路径
ffmpeg_path = os.path.join(os.path.dirname(__file__), 'Tools', 'ffmpeg', 'bin', 'ffmpeg.exe')
token = config['token']


# endregion
# region 网易API部分
async def search_netease_music(keyword: str):
    # aiohttp调用网易云音乐API localhost:3000/search?keywords=keyword
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://localhost:3000/search?keywords={keyword}') as resp:
                data = await resp.json()
                if data['code'] == 200:
                    songs = data['result']['songs']
                    if songs:
                        # 格式化为指定的字符串格式，每行一首歌曲
                        formatted_songs = "\n".join([
                            # f"歌曲ID:{song['id']} 歌名:{song['name']} 歌手:{song['artists'][0]['name']}"
                            f"{song['name']} - {song['artists'][0]['name']}"
                            for song in songs[:15]  # 限制为最多15条
                        ])
                        print(songs)
                        return formatted_songs
                    else:
                        return "未找到相关音乐"
                else:
                    raise Exception("调用 API 失败")
    except Exception as e:
        raise Exception(e)


# 检查登录状态/login/status
async def check_login_status():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:3000/login/status') as resp:
            data = await resp.json()
            # 访问 data['data']['code']，因为 'code' 键嵌套在 'data' 中
            if data['data']['code'] == 200:
                profile = data['data']['profile']
                # 需要确认 profile 是否为 None，避免 KeyError
                if profile is not None:
                    print(profile)
                    return
                else:
                    print("未登录")
                    return None
            else:
                print("未登录")
                return None


# 退出登录/logout
async def logout():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:3000/logout') as resp:
            data = await resp.json()
            if data['code'] == 200:
                return "已退出登录"
            else:
                return "退出登录失败"


# 游客登录/register/anonimous
async def register_anonimous():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:3000/register/anonimous') as resp:
            data = await resp.json()
            if data['code'] == 200:
                return "已登录为游客"
            else:
                return None


async def get_login_status(session, cookie):
    try:
        status_response = await session.post(
            f'http://localhost:3000/login/status?timestamp={int(asyncio.get_event_loop().time() * 1000)}',
            json={"cookie": cookie})
        status_data = await status_response.json()
        print("登录状态：", status_data)
    except Exception as e:
        print(f"获取登录状态失败：{e}")


def render_qr_to_console(data):
    qr = QRCode()
    qr.add_data(data)
    qr.make(fit=True)
    qr_console = qr.make_image(fill_color="black", back_color="white")
    qr_console.show()


async def qrcode_login():
    """通过二维码登录并保存有效的 Cookie"""
    async with aiohttp.ClientSession() as session:
        try:
            # 获取二维码唯一标识 key
            key_response = await session.get(
                f'http://localhost:3000/login/qr/key?timestamp={int(asyncio.get_event_loop().time() * 1000)}')
            key_data = await key_response.json()
            key = key_data.get('data', {}).get('unikey')
            if not key:
                return "获取二维码 key 失败"

            # 生成二维码
            qr_response = await session.get(
                f'http://localhost:3000/login/qr/create?key={key}&qrimg=true&timestamp={int(asyncio.get_event_loop().time() * 1000)}')
            qr_data = await qr_response.json()
            qr_url = qr_data.get('data', {}).get('qrurl')
            if not qr_url:
                return "生成二维码失败"

            # 渲染二维码到控制台
            render_qr_to_console(qr_url)

            # 轮询二维码登录状态
            while True:
                await asyncio.sleep(3)
                status_response = await session.get(
                    f'http://localhost:3000/login/qr/check?key={key}&timestamp={int(asyncio.get_event_loop().time() * 1000)}')
                status_data = await status_response.json()

                if status_data.get('code') == 800:
                    return "二维码已过期，请重新生成"
                elif status_data.get('code') == 803:
                    # 登录成功，提取 Cookie
                    cookie_header = status_data.get('cookie')
                    cookies = parse_cookie_header(cookie_header)
                    await save_cookies(cookies)
                    return "登录成功"
                elif status_data.get('code') == 801:
                    print("等待用户扫描二维码...")
        except Exception as e:
            return f"发生错误：{e}"


def parse_cookie_header(cookie_header: str) -> dict:
    """解析并仅保留指定的 Cookie 字段"""
    allowed_keys = {"MUSIC_A_T", "MUSIC_R_T", "__csrf", "NMTID", "MUSIC_SNS", "MUSIC_U"}
    cookies = {}
    for item in cookie_header.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in allowed_keys:  # 只保留指定的字段
                cookies[key] = value
    return cookies


async def save_cookies(cookies: dict):
    """保存 Cookie 到文件"""
    with open("cookie.json", "w") as f:
        json.dump(cookies, f)  # type: ignore


async def load_cookies() -> dict:
    """从文件加载 Cookie"""
    try:
        with open("cookie.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


async def session_is_valid() -> bool:
    """检查当前保存的 Cookie 是否有效"""
    cookies = await load_cookies()
    if not cookies:
        return False

    async with aiohttp.ClientSession(cookies=cookies) as session:
        try:
            # 使用 /login/status 检查登录状态
            async with session.get("http://localhost:3000/login/status") as resp:
                data = await resp.json()
                if data.get("data", {}).get("code") == 200:
                    return True
        except Exception as e:
            print(e)
            pass
    return False


async def ensure_logged_in():
    """确保用户已登录"""
    if not await session_is_valid():
        print("Cookie 无效或已过期")
        return "Cookie不存在或过期，请通知开发者重新登录"
    else:
        a = "网易API Cookie有效"
        return a


async def download_music(keyword: str):
    try:
        # 确保已登录
        await ensure_logged_in()

        # 加载 Cookie
        cookies = await load_cookies()
        if not cookies:
            return "未登录，请通知开发者完成登录操作"

        # 使用有效的 Cookie 创建会话
        async with aiohttp.ClientSession(cookies=cookies) as session:
            # 搜索歌曲
            async with session.get(f"http://localhost:3000/search?keywords={keyword}") as resp:
                data = await resp.json()
                if data['code'] != 200:
                    raise Exception("调用搜索 API 失败")

                # 检查搜索结果
                songs = data.get('result', {}).get('songs', [])
                if not songs:
                    return "未找到相关歌曲"

                # 下载逻辑
                first_song = songs[0]
                song_id = first_song['id']
                song_name = first_song['name']
                artist_name = ", ".join(artist['name'] for artist in first_song['artists'])
                album_name = first_song['album']['name']

                async with session.get(
                        f"http://localhost:3000/song/download/url/v1?id={song_id}&level=higher") as download_resp:
                    download_data = await download_resp.json()
                    if download_data['code'] != 200 or not download_data['data']['url']:
                        print("无法获取下载链接")
                        return "无法获取下载链接，可能需要 VIP 权限"

                    download_url = download_data['data']['url']
                    file_name = f"./AudioLib/{song_name} - {artist_name} ({album_name}).mp3"
                    os.makedirs(os.path.dirname(file_name), exist_ok=True)

                    # 下载文件
                    async with session.get(download_url) as music_resp:
                        with open(file_name, 'wb') as f:
                            f.write(await music_resp.read())
                            print(f"歌曲已下载: {song_name} - {artist_name} ({album_name})")
                    return (f"歌曲已下载: {song_name} - {artist_name} ({album_name}\n"
                            f"URL: {download_url}")
    except Exception as e:
        return f"发生错误: {e}"


# endregion

# region 点歌功能部分
keep_alive_tasks = {}


async def get_alive_channel_list():
    client = KookVoiceClient(token)
    try:
        # 获取频道列表示例
        list_data = await client.list_channels()
        return list_data  # Return the actual data for processing
    except VoiceClientError as e:
        return {"error": str(e)}
    finally:
        await client.close()


async def join_channel(channel_id):
    client = KookVoiceClient(token, channel_id)
    try:
        # 加入语音频道示例
        join_data = await client.join_channel()
        return {"success": join_data}
    except VoiceClientError as e:
        return {"error": str(e)}
    finally:
        await client.close()


async def leave_channel(channel_id):
    client = KookVoiceClient(token, channel_id)
    try:
        # 离开语音频道示例
        leave_data = await client.leave_channel()
        return {"success": leave_data}
    except VoiceClientError as e:
        return {"error": str(e)}
    finally:
        await client.close()


def is_bot_in_channel(alive_data, channel_id):
    if 'error' in alive_data:
        return False, alive_data['error']
    for item in alive_data.get('items', []):
        if item['id'] == channel_id:
            return True, None
    return False, None


async def keep_channel_alive(channel_id):
    client = KookVoiceClient(token, channel_id)
    while True:
        try:
            await client.keep_alive(channel_id)
            print(f"保持频道 {channel_id} 活跃成功")
        except VoiceClientError as e:
            # 处理错误，例如记录日志或尝试重新连接
            print(f"保持频道 {channel_id} 活跃时出错: {e}")
        await asyncio.sleep(40)  # 等待40秒后再次调用

# endregion
