import aiohttp
import asyncio
import json
import os
from qrcode.main import QRCode

# API连接错误检测
def is_api_connection_error(error_msg: str) -> bool:
    """
    检查错误是否为API连接错误
    
    Args:
        error_msg: 错误信息字符串
        
    Returns:
        是否为API连接错误
    """
    connection_error_patterns = [
        "Cannot connect to host localhost", 
        "Connection refused", 
        "拒绝网络连接",
        "连接尝试失败",
        "No route to host",
        "Failed to establish a new connection",
        "没有到主机的路由"
    ]
    
    return any(pattern in error_msg for pattern in connection_error_patterns)

def get_api_error_message() -> str:
    """
    获取API连接错误的友好提示消息
    
    Returns:
        友好的错误消息
    """
    return "❌ 网易云音乐API服务未启动！\n请先启动NeteaseCloudMusicApi服务 (localhost:3000)\n如果您是服务器用户，请联系机器人管理员启动API服务。"

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
                        # 获取第一首歌曲的ID
                        first_song_id = str(songs[0]['id'])
                        
                        # 格式化为指定的字符串格式，每行一首歌曲
                        formatted_songs = "\n".join([
                            # f"歌曲ID:{song['id']} 歌名:{song['name']} 歌手:{song['artists'][0]['name']}"
                            f"{song['name']} - {song['artists'][0]['name']}"
                            for song in songs[:15]  # 限制为最多15条
                        ])
                        print(songs)
                        
                        # 返回包含歌曲列表和第一首歌曲ID的字典
                        return {
                            "formatted_list": formatted_songs,
                            "first_song_id": first_song_id
                        }
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


# 获取登陆状态
async def get_login_status(session, cookie):
    try:
        status_response = await session.post(
            f'http://localhost:3000/login/status?timestamp={int(asyncio.get_event_loop().time() * 1000)}',
            json={"cookie": cookie})
        status_data = await status_response.json()
        print("登录状态：", status_data)
    except Exception as e:
        print(f"获取登录状态失败：{e}")


# 展示二维码
def render_qr_to_console(data):
    qr = QRCode()
    qr.add_data(data)
    qr.make(fit=True)
    qr_console = qr.make_image(fill_color="black", back_color="white")
    qr_console.show()


# 二维码登录
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


# 解析 Cookie 字段
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


# 保存 Cookie 到文件
async def save_cookies(cookies: dict):
    """保存 Cookie 到文件"""
    with open("cookie.json", "w") as f:
        json.dump(cookies, f)  # type: ignore


# 从文件加载 Cookie
async def load_cookies() -> dict:
    """从文件加载 Cookie"""
    try:
        with open("cookie.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# 检查当前保存的 Cookie 是否有效
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


# 确保用户已登录
async def ensure_logged_in():
    """确保用户已登录"""
    if not await session_is_valid():
        print("Cookie 无效或已过期")
        return "Cookie不存在或过期，请通知开发者重新登录"
    else:
        status = "网易API Cookie有效"
        return status


# 检查歌曲是否已经存在于本地
def is_song_exists(song_id: str) -> tuple[bool, str]:
    """
    检查指定ID的歌曲是否已经存在于本地
    
    Args:
        song_id: 歌曲ID
        
    Returns:
        (存在标志, 文件路径): 如果存在返回(True, 文件路径)，否则返回(False, "")
    """
    relative_path = "./AudioLib"
    absolute_path = os.path.abspath(relative_path)
    file_path = os.path.join(absolute_path, f"{song_id}.mp3")
    file_path = os.path.normpath(file_path)
    
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return True, file_path
    return False, ""


# 下载音乐
async def download_music(keyword: str):
    try:
        # 确保已登录
        await ensure_logged_in()

        # 加载 Cookie
        cookies = await load_cookies()
        if not cookies:
            return {"error": "未登录，请通知开发者完成登录操作"}

        async with aiohttp.ClientSession(cookies=cookies) as session:
            # 搜索歌曲
            async with session.get(f"http://localhost:3000/search?keywords={keyword}") as resp:
                data = await resp.json()
                if data['code'] != 200:
                    raise Exception("调用搜索 API 失败")

                # 检查搜索结果
                songs = data.get('result', {}).get('songs', [])
                if not songs:
                    return {"error": "未找到相关歌曲"}

                # 提取歌曲信息
                first_song = songs[0]
                song_id = str(first_song['id'])
                song_name = first_song['name']
                artist_name = ", ".join(artist['name'] for artist in first_song['artists'])
                album_name = first_song['album']['name']
                
                print(f"搜索到歌曲: {song_name} - {artist_name} (ID: {song_id})")
                
                # 检查歌曲是否已存在
                is_exists, file_name = is_song_exists(song_id)
                if is_exists:
                    print(f"歌曲 {song_name} (ID: {song_id}) 已存在，跳过下载")
                    return {
                        "file_name": file_name,
                        "download_url": "使用本地缓存",
                        "song_name": song_name,
                        "artist_name": artist_name,
                        "album_name": album_name,
                        "cached": True
                    }

                # 下载新歌曲
                print(f"开始下载歌曲 {song_name} (ID: {song_id})")
                relative_path = "./AudioLib"
                absolute_path = os.path.abspath(relative_path)

                # 直接使用已获取的song_id，不需要再次搜索
                async with session.get(
                        f"http://localhost:3000/song/download/url/v1?id={song_id}&level=higher") as download_resp:
                    download_data = await download_resp.json()
                    if download_data['code'] != 200 or not download_data['data']['url']:
                        return {"error": "无法获取下载链接，可能需要 VIP 权限"}

                    download_url = download_data['data']['url']
                    file_name = os.path.join(absolute_path, f"{song_id}.mp3")
                    os.makedirs(os.path.dirname(file_name), exist_ok=True)

                    # 下载文件
                    file_name = os.path.normpath(file_name)
                    async with session.get(download_url) as music_resp:
                        with open(file_name, 'wb') as f:
                            f.write(await music_resp.read())

                    return {
                        "file_name": file_name,
                        "download_url": download_url,
                        "song_name": song_name,
                        "artist_name": artist_name,
                        "album_name": album_name,
                        "cached": False
                    }
    except Exception as e:
        return {"error": str(e)}


# 通过ID直接下载歌曲
async def download_music_by_id(song_id: str):
    try:
        # 确保已登录
        await ensure_logged_in()

        # 检查歌曲是否已存在
        is_exists, file_path = is_song_exists(song_id)
        if is_exists:
            # 如果歌曲已存在，获取歌曲信息但不重新下载
            # 加载 Cookie
            cookies = await load_cookies()
            if not cookies:
                return {"error": "未登录，请通知开发者完成登录操作"}
                
            async with aiohttp.ClientSession(cookies=cookies) as session:
                # 获取歌曲详情
                async with session.get(f"http://localhost:3000/song/detail?ids={song_id}") as detail_resp:
                    detail_data = await detail_resp.json()
                    if detail_data['code'] != 200:
                        return {"error": "获取歌曲详情失败"}
                    
                    # 提取歌曲信息
                    song_info = detail_data.get('songs', [])
                    if not song_info:
                        return {"error": f"未找到ID为 {song_id} 的歌曲"}
                    
                    song_info = song_info[0]
                    song_name = song_info['name']
                    artist_name = ", ".join(artist['name'] for artist in song_info['ar'])
                    album_name = song_info['al']['name']
                    
                    print(f"歌曲 {song_name} (ID: {song_id}) 已存在，跳过下载")
                    return {
                        "file_name": file_path,
                        "download_url": "使用本地缓存",
                        "song_name": song_name,
                        "artist_name": artist_name,
                        "album_name": album_name,
                        "cached": True
                    }

        # 如果歌曲不存在，进行常规下载流程
        # 加载 Cookie
        cookies = await load_cookies()
        if not cookies:
            return {"error": "未登录，请通知开发者完成登录操作"}

        async with aiohttp.ClientSession(cookies=cookies) as session:
            # 获取歌曲详情
            async with session.get(f"http://localhost:3000/song/detail?ids={song_id}") as detail_resp:
                detail_data = await detail_resp.json()
                if detail_data['code'] != 200:
                    return {"error": "获取歌曲详情失败"}
                
                # 提取歌曲信息
                song_info = detail_data.get('songs', [])
                if not song_info:
                    return {"error": f"未找到ID为 {song_id} 的歌曲"}
                
                song_info = song_info[0]
                song_name = song_info['name']
                artist_name = ", ".join(artist['name'] for artist in song_info['ar'])
                album_name = song_info['al']['name']
                
                # 获取下载链接
                async with session.get(
                        f"http://localhost:3000/song/download/url/v1?id={song_id}&level=higher") as download_resp:
                    download_data = await download_resp.json()
                    if download_data['code'] != 200 or not download_data['data']['url']:
                        return {"error": "无法获取下载链接，可能需要 VIP 权限"}

                    download_url = download_data['data']['url']
                    relative_path = "./AudioLib"
                    absolute_path = os.path.abspath(relative_path)
                    file_name = os.path.join(absolute_path, f"{song_id}.mp3")
                    os.makedirs(os.path.dirname(file_name), exist_ok=True)

                    # 下载文件
                    file_name = os.path.normpath(file_name)
                    async with session.get(download_url) as music_resp:
                        with open(file_name, 'wb') as f:
                            f.write(await music_resp.read())

                    return {
                        "file_name": file_name,
                        "download_url": download_url,
                        "song_name": song_name,
                        "artist_name": artist_name,
                        "album_name": album_name,
                        "cached": False
                    }
    except Exception as e:
        return {"error": str(e)}


# 仅获取歌曲的URL，不下载
async def get_song_url(song_id: str):
    """
    获取歌曲的播放URL，无论歌曲是否已在本地缓存
    
    Args:
        song_id: 歌曲ID
        
    Returns:
        包含歌曲URL和详情的字典
    """
    try:
        # 确保已登录
        await ensure_logged_in()
        
        # 加载Cookie
        cookies = await load_cookies()
        if not cookies:
            return {"error": "未登录，请通知开发者完成登录操作"}
            
        async with aiohttp.ClientSession(cookies=cookies) as session:
            # 获取歌曲详情
            async with session.get(f"http://localhost:3000/song/detail?ids={song_id}") as detail_resp:
                detail_data = await detail_resp.json()
                if detail_data['code'] != 200:
                    return {"error": "获取歌曲详情失败"}
                
                # 提取歌曲信息
                song_info = detail_data.get('songs', [])
                if not song_info:
                    return {"error": f"未找到ID为 {song_id} 的歌曲"}
                
                song_info = song_info[0]
                song_name = song_info['name']
                artist_name = ", ".join(artist['name'] for artist in song_info['ar'])
                album_name = song_info['al']['name']
                album_pic = song_info.get('al', {}).get('picUrl', '')
                
                # 获取播放链接
                async with session.get(
                        f"http://localhost:3000/song/url?id={song_id}&br=320000") as url_resp:
                    url_data = await url_resp.json()
                    if url_data['code'] != 200 or not url_data.get('data') or not url_data['data'][0].get('url'):
                        # 尝试获取下载链接作为备用
                        async with session.get(
                                f"http://localhost:3000/song/download/url/v1?id={song_id}&level=higher") as download_resp:
                            download_data = await download_resp.json()
                            if download_data['code'] != 200 or not download_data['data'].get('url'):
                                return {"error": "无法获取歌曲链接，可能需要VIP权限"}
                            song_url = download_data['data']['url']
                    else:
                        song_url = url_data['data'][0]['url']
                
                # 检查是否本地已缓存（仅用于信息返回，不影响URL获取）
                is_cached, file_path = is_song_exists(song_id)
                
                return {
                    "song_url": song_url,
                    "song_name": song_name,
                    "artist_name": artist_name,
                    "album_name": album_name,
                    "album_pic": album_pic,
                    "cached": is_cached,
                    "file_path": file_path if is_cached else ""
                }
    except Exception as e:
        if is_api_connection_error(str(e)):
            return {"error": get_api_error_message()}
        return {"error": str(e)}


# 检查电台节目是否已经存在于本地
def is_radio_program_exists(program_id: str) -> tuple[bool, str]:
    """
    检查指定ID的电台节目是否已经存在于本地
    
    Args:
        program_id: 电台节目ID
        
    Returns:
        (存在标志, 文件路径): 如果存在返回(True, 文件路径)，否则返回(False, "")
    """
    relative_path = "./AudioLib/Radio"
    absolute_path = os.path.abspath(relative_path)
    file_path = os.path.join(absolute_path, f"{program_id}.mp3")
    file_path = os.path.normpath(file_path)
    
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return True, file_path
    return False, ""


# 获取电台节目详情并下载
async def download_radio_program(program_id: str):
    """
    获取电台节目详情并下载电台节目
    
    Args:
        program_id: 电台节目ID
        
    Returns:
        包含电台节目信息和文件路径的字典
    """
    try:
        # 确保已登录
        await ensure_logged_in()
        
        # 检查节目是否已存在
        is_exists, file_path = is_radio_program_exists(program_id)
        if is_exists:
            # 如果节目已存在，获取节目信息但不重新下载
            # 加载 Cookie
            cookies = await load_cookies()
            if not cookies:
                return {"error": "未登录，请通知开发者完成登录操作"}
                
            async with aiohttp.ClientSession(cookies=cookies) as session:
                # 获取电台节目详情
                async with session.get(f"http://localhost:3000/dj/program/detail?id={program_id}") as detail_resp:
                    detail_data = await detail_resp.json()
                    if detail_data['code'] != 200:
                        return {"error": "获取电台节目详情失败"}
                    
                    # 提取节目信息
                    program_info = detail_data.get('program', {})
                    if not program_info:
                        return {"error": f"未找到ID为 {program_id} 的电台节目"}
                    
                    program_name = program_info['name']
                    radio_name = program_info['radio']['name']
                    dj_name = program_info['dj']['nickname']
                    description = program_info.get('description', "")
                    
                    print(f"电台节目 {program_name} (ID: {program_id}) 已存在，跳过下载")
                    return {
                        "file_name": file_path,
                        "download_url": "使用本地缓存",
                        "song_name": program_name,
                        "artist_name": dj_name,
                        "album_name": radio_name,
                        "description": description,
                        "cached": True,
                        "is_radio": True
                    }
                    
        # 如果节目不存在，进行下载流程
        # 加载 Cookie
        cookies = await load_cookies()
        if not cookies:
            return {"error": "未登录，请通知开发者完成登录操作"}
            
        async with aiohttp.ClientSession(cookies=cookies) as session:
            # 获取电台节目详情
            async with session.get(f"http://localhost:3000/dj/program/detail?id={program_id}") as detail_resp:
                detail_data = await detail_resp.json()
                if detail_data['code'] != 200:
                    return {"error": "获取电台节目详情失败"}
                
                # 提取节目信息
                program_info = detail_data.get('program', {})
                if not program_info:
                    return {"error": f"未找到ID为 {program_id} 的电台节目"}
                
                program_name = program_info['name']
                radio_name = program_info['radio']['name']
                dj_name = program_info['dj']['nickname']
                description = program_info.get('description', "")
                main_track_id = program_info['mainTrackId']
                
                print(f"获取到电台节目: {program_name} (ID: {program_id}, 主曲目ID: {main_track_id})")
                
                # 使用主曲目ID获取下载链接
                async with session.get(
                        f"http://localhost:3000/song/download/url/v1?id={main_track_id}&level=higher") as download_resp:
                    download_data = await download_resp.json()
                    if download_data['code'] != 200 or not download_data['data']['url']:
                        return {"error": "无法获取下载链接，可能需要 VIP 权限"}

                    download_url = download_data['data']['url']
                    relative_path = "./AudioLib/Radio"
                    absolute_path = os.path.abspath(relative_path)
                    os.makedirs(absolute_path, exist_ok=True)  # 确保Radio文件夹存在
                    file_name = os.path.join(absolute_path, f"{program_id}.mp3")
                    
                    # 下载文件
                    file_name = os.path.normpath(file_name)
                    async with session.get(download_url) as music_resp:
                        with open(file_name, 'wb') as f:
                            f.write(await music_resp.read())
                    
                    return {
                        "file_name": file_name,
                        "download_url": download_url,
                        "song_name": program_name,
                        "artist_name": dj_name,
                        "album_name": radio_name,
                        "description": description,
                        "cached": False,
                        "is_radio": True
                    }
    except Exception as e:
        return {"error": str(e)}


# endregion

# region 网易云歌单相关功能
async def get_playlist_detail(playlist_id: str):
    """
    获取歌单详情信息
    
    Args:
        playlist_id: 歌单ID
        
    Returns:
        歌单详情信息
    """
    try:
        # 确保已登录
        await ensure_logged_in()
        
        # 加载Cookie
        cookies = await load_cookies()
        if not cookies:
            return {"error": "未登录，请通知开发者完成登录操作"}
        
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(f"http://localhost:3000/playlist/detail?id={playlist_id}") as resp:
                data = await resp.json()
                if data['code'] != 200:
                    raise Exception("获取歌单详情失败")
                
                return data
    except Exception as e:
        if is_api_connection_error(str(e)):
            return {"error": get_api_error_message()}
        return {"error": str(e)}

async def get_song_detail(song_id: str):
    """
    获取歌曲详细信息
    
    Args:
        song_id: 歌曲ID
        
    Returns:
        歌曲详细信息
    """
    try:
        # 确保已登录
        await ensure_logged_in()
        
        # 加载Cookie
        cookies = await load_cookies()
        if not cookies:
            return {"error": "未登录，请通知开发者完成登录操作"}
        
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(f"http://localhost:3000/song/detail?ids={song_id}") as resp:
                data = await resp.json()
                if data['code'] != 200:
                    raise Exception("获取歌曲详情失败")
                
                # 如果成功获取到歌曲信息
                if data.get('songs') and len(data['songs']) > 0:
                    song_info = data['songs'][0]
                    
                    # 提取重要信息
                    result = {
                        'name': song_info.get('name', ''),
                        'id': song_info.get('id', ''),
                        'duration': song_info.get('dt', 0) / 1000,  # 转换为秒
                        'artists': [],
                        'album': {
                            'name': '',
                            'id': '',
                            'picUrl': ''
                        }
                    }
                    
                    # 提取艺术家信息
                    if song_info.get('ar'):
                        for artist in song_info['ar']:
                            result['artists'].append({
                                'name': artist.get('name', ''),
                                'id': artist.get('id', '')
                            })
                    
                    # 提取专辑信息
                    if song_info.get('al'):
                        album = song_info['al']
                        result['album'] = {
                            'name': album.get('name', ''),
                            'id': album.get('id', ''),
                            'picUrl': album.get('picUrl', '')
                        }
                    
                    return result
                else:
                    return {"error": f"未找到ID为 {song_id} 的歌曲"}
    except Exception as e:
        if is_api_connection_error(str(e)):
            return {"error": get_api_error_message()}
        return {"error": str(e)}

async def get_playlist_tracks(playlist_id: str, limit: int = 20, offset: int = 0):
    """
    获取歌单中的歌曲列表
    
    Args:
        playlist_id: 歌单ID
        limit: 每次获取的歌曲数量，默认20首
        offset: 偏移量，默认0（第一首歌从0开始计数）
        
    Returns:
        歌单中的歌曲列表
    """
    try:
        # 确保已登录
        await ensure_logged_in()
        
        # 加载Cookie
        cookies = await load_cookies()
        if not cookies:
            return {"error": "未登录，请通知开发者完成登录操作"}
        
        # 确保参数有效
        if limit <= 0:
            limit = 20
        if offset < 0:
            offset = 0
            
        # 构建API URL，显式加入时间戳避免缓存
        timestamp = int(asyncio.get_event_loop().time() * 1000)
        api_url = f"http://localhost:3000/playlist/track/all?id={playlist_id}&limit={limit}&offset={offset}&timestamp={timestamp}"
        
        print(f"请求歌单tracks: {api_url}")
        
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(api_url) as resp:
                data = await resp.json()
                if data['code'] != 200:
                    raise Exception(f"获取歌单歌曲列表失败，错误码: {data['code']}")
                
                # 打印调试信息
                print(f"获取到 {len(data.get('songs', []))} 首歌曲")
                
                return data
    except Exception as e:
        if is_api_connection_error(str(e)):
            return {"error": get_api_error_message()}
        return {"error": str(e)}

# 解析网易云音乐歌单URL
def parse_playlist_url(url: str) -> str:
    """
    解析网易云音乐歌单URL，提取歌单ID
    
    Args:
        url: 歌单URL
        
    Returns:
        歌单ID或空字符串（如果不是有效的歌单URL）
    """
    import re
    
    # 使用search而不是match，并且只匹配id参数部分
    pattern = r'music\.163\.com/(?:[^/]*(?:/)?)?playlist\?(?:[^&]*&)*id=(\d+)'
    
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    
    return ""
# endregion