import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta

from khl import Bot, Message
from khl.card import Card, CardMessage, Element, Module, Types

import NeteaseAPI
import core
from client_manager import keep_alive_tasks, stream_tasks, stream_monitor_tasks
from core import search_files
from funnyAPI import we, local_hitokoto  # , get_hitokoto


# region 初始化进程
def open_file(path: str):
    # 检查文件是否存在
    if not os.path.exists(path):
        print(f"错误: 文件 '{path}' 不存在。")
        return None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            tmp = json.load(f)
        return tmp
    except FileNotFoundError:
        print(f"错误: 文件 '{path}' 找不到。")
        return None
    except json.JSONDecodeError:
        print(f"错误: 文件 '{path}' 包含无效的 JSON 格式。")
        return None
    except Exception as e:
        print(f"发生了一个意外错误: {e}")
        return None


# 打开config.json并进行检测
config = open_file('./config/config.json')
if config is None:
    # 文件不存在或加载出错时，停止程序
    print("加载配置文件失败，程序退出。")
    exit(1)  # 或者使用 break 来终止循环或程序

# 初始化机器人
bot = Bot(token=config['token'])  # 默认采用 websocket
token = config['token']


def get_time():
    return time.strftime("%y-%m-%d %H:%M:%S", time.localtime())


start_time = get_time()


# endregion

# region 基础功能
@bot.command(name='menu', aliases=['帮助', '菜单', "help"])
async def menu(msg: Message):
    cm = CardMessage()
    c3 = Card(
        Module.Header('你可以用下面这些指令呼叫我哦！'),
        Module.Context(
            Element.Text(f"开源代码见[Github](https://github.com/e8xl/Howard_Please_Dont_Sing),"
                         f"\n机器人启动时间: [{start_time}]\n"
                         f"娱乐部分参考项目[Ahri](https://github.com/Aewait/Valorant-Kook-Bot)"
                         f"丨音频部分（自己攒的）[Kook_VoiceAPI](https://github.com/e8xl/Kook_VoiceAPI)"
                         f"\n感恩奉献:)",
                         Types.Text.KMD)))
    c3.append(Module.Section('「菜单」「帮助」都可以呼叫我\n'))
    c3.append(Module.Divider())  # 分割线
    c3.append(Module.Header('歌姬最重要的不是要唱歌吗??'))
    text = "「点歌 歌名」即可完成点歌任务\n"
    text += "「搜索 歌名-歌手(可选)」搜索音乐\n"
    text += "「下载 歌名-歌手(可选)」下载音乐（不要滥用球球了）"
    c3.append(Module.Section(Element.Text(text, Types.Text.KMD)))
    c3.append(Module.Divider())  # 分割线
    c3.append(Module.Header('和我玩小游戏吧~ '))
    text = "「r 1 100」掷骰子1-100，范围可自主调节。可在末尾添加第三个参数实现同时掷多个骰子\n"
    text += "「cd 秒数」倒计时，默认60秒\n"
    text += "「we 城市」查询城市未来3天的天气情况\n"
    c3.append(Module.Section(Element.Text(text, Types.Text.KMD)))
    c3.append(Module.Divider())
    c3.append(
        Module.Section('帮我Github点个Star吧~', Element.Button('让我看看', 'https://www.8xl.icu', Types.Click.LINK)))
    c3.append(Module.Section('赞助一下吧~', Element.Button("赞助一下", 'https://afdian.com/a/888xl', Types.Click.LINK)))
    c3.append(Module.Section('加入服务器反馈BUG（积极反馈 球球了）',
                             Element.Button("加入服务器", 'https://kook.vip/fYM28v', Types.Click.LINK)))
    """
    在线一言API会导致菜单响应速度过慢 参考服务器与API调用所影响 可以删除下面c3.append到KMD)))
    """
    '''
    c3.append(Module.Context(
        Element.Text(f"{await get_hitokoto()}", Types.Text.KMD)  # 插入一言功能
    ))
    '''

    c3.append(Module.Context(
        Element.Text(f"{await local_hitokoto()}", Types.Text.KMD)  # 插入一言功能
    ))

    cm.append(c3)
    await msg.reply(cm)
    await bot.client.update_playing_game(2128858)


# 娱乐项目
# 摇骰子
@bot.command(name='r', aliases=['roll'])
async def r(msg: Message, t_min: int = 1, t_max: int = 100, n: int = 1, *args):
    if args != ():
        await msg.reply(f"参数错误")
        return
    elif t_min >= t_max:  # 范围小边界不能大于大边界
        await msg.reply(f'范围错误，必须提供两个参数，由小到大！\nmin:`{t_min}` max:`{t_max}`')
        return
    elif t_max >= 9999:  # 不允许用户使用太大的数字
        await msg.reply(f"掷骰子的数据超出范围！")
        return

    result = [random.randint(t_min, t_max) for _ in range(n)]
    await msg.reply(f'掷出来啦: {result}')


# 秒表
# 倒计时函数，单位为秒，默认60秒
@bot.command(name='cd', aliases=['倒计时', 'countdown'])
async def cd(msg: Message, countdown_second: int = 60, *args):
    if args != ():
        await msg.reply(f"参数错误，countdown命令只支持1个参数\n正确用法: `countdown 120` 生成一个120s的倒计时")
        return
    elif countdown_second <= 0 or countdown_second >= 90000000:
        await msg.reply(f"倒计时时间超出范围！")
        return
    cm = CardMessage()
    c1 = Card(Module.Header('帮你按下秒表喽~'), color=(198, 65, 55))  # color=(90,59,215) is another available form
    c1.append(Module.Divider())
    c1.append(
        Module.Countdown(datetime.now() + timedelta(seconds=countdown_second), mode=Types.CountdownMode.SECOND))
    cm.append(c1)
    await msg.reply(cm)


# 天气
@bot.command(name='we', aliases=["天气", "weather"])
async def we_command(msg: Message, city: str = "err"):
    await we(msg, city)  # 调用we函数


# endregion

# region 点歌指令操作

# 加入频道 (Test)
@bot.command(name="join")
async def play(msg: Message, *args):
    # 检查列表中的频道，以确保机器人不会重复加入同一频道
    alive_data = await core.get_alive_channel_list()
    if 'error' in alive_data:
        await msg.reply(f"获取频道列表时发生错误: {alive_data['error']}")
        return

    # 确定要加入的频道
    if args:
        target_channel_id = args[0]
    else:
        # 获取用户当前所在的语音频道
        user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
        if not user_channels:
            await msg.reply('使用参考：join/join {channel_id} 请先加入一个语音频道或提供频道ID后再使用点歌功能')
            return
        target_channel_id = user_channels[0].id

    # 检测机器人是否在目标频道中
    is_in_channel, error = core.is_bot_in_channel(alive_data, target_channel_id)
    if error:
        await msg.reply(f"检查频道状态时发生错误: {error}")
        return

    if is_in_channel:
        # 机器人已在目标频道中，尝试离开
        leave_result = await core.leave_channel(target_channel_id)
        if 'error' in leave_result:
            await msg.reply(f"尝试离开频道时发生错误: {leave_result['error']}")
            return
        # 重新获取频道列表，以确保机器人已离开
        alive_data = await core.get_alive_channel_list()
        is_in_channel, error = core.is_bot_in_channel(alive_data, target_channel_id)
        if is_in_channel:
            await msg.reply("离开频道失败，请稍后再试。")
            return
        elif error:
            await msg.reply(f"检查频道状态时发生错误: {error}")
            return

    # 尝试加入目标频道
    join_result = await core.join_channel(target_channel_id)
    if 'error' in join_result:
        await msg.reply(f"加入频道失败: {join_result['error']}")
    else:
        await msg.reply(f"成功加入频道: {target_channel_id}\n{join_result}")
        if target_channel_id not in keep_alive_tasks:
            task = asyncio.create_task(core.keep_channel_alive(target_channel_id))
            keep_alive_tasks[target_channel_id] = task


# noinspection PyUnresolvedReferences

@bot.command(name="exit", aliases=["leave", "退出"])
async def exit_command(msg: Message, *args):
    # 确定离开的频道
    if args:
        try:
            target_channel_id = int(args[0])
        except ValueError:
            await msg.reply("提供的频道ID无效，请确保提供的是数字ID。")
            return
    else:
        # 获取用户当前所在的语音频道
        user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
        if not user_channels:
            await msg.reply('请先加入一个语音频道或提供频道ID后再使用退出功能')
            return
        target_channel_id = user_channels[0].id

    try:
        # 使用重构后的退出函数
        leave_result = await core.leave_channel(target_channel_id)
        if 'error' in leave_result:
            await msg.reply(f"退出频道失败: {leave_result['error']}")
        else:
            await msg.reply(f"已成功退出频道: {target_channel_id}")
    except Exception as e:
        logger.error(f"退出频道时发生错误: {e}")
        await msg.reply(f"退出频道时发生错误: {e}")
    finally:
        # 取消保持活跃任务
        task = keep_alive_tasks.pop(target_channel_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"保持活跃任务 {target_channel_id} 已被取消。")

        # 取消推流任务
        streamer = stream_tasks.pop(target_channel_id, None)
        if streamer:
            try:
                await streamer.stop()
                # await msg.reply(f"已停止推流并取消相关任务: {target_channel_id}")
            except Exception as e:
                logger.error(f"停止推流任务时发生错误: {e}")
                try:
                    await msg.reply(f"停止推流任务时发生错误: {e}")
                except Exception as reply_error:
                    logger.error(f"发送停止推流错误消息时发生错误: {reply_error}")


@bot.command(name="alive", aliases=['ping'])
async def alive_command(msg: Message):
    try:
        alive_data = await core.get_alive_channel_list()
        if 'error' in alive_data:
            await msg.reply(f"获取频道列表时发生错误: {alive_data['error']}")
        else:
            await msg.reply(f'获取频道列表成功: {json.dumps(alive_data, ensure_ascii=False)}')
    except Exception as e:
        await msg.reply(f"发生错误: {e}")


# 本地搜索(test)
@bot.command(name="ls")
async def ls_command(msg: Message, *args):
    try:
        search_keyword = " ".join(args)
        search_file = await search_files(search_keyword=search_keyword)
        print(search_file)

    except Exception as e:
        await msg.reply(f"发生错误:{e}")


@bot.command(name="play", aliases=["点歌", "p"])
async def neteasemusic_stream(msg: Message, *args):
    if not args:
        await msg.reply("参数缺失，请提供一个搜索关键字，例如：test 周杰伦")
        return

    try:
        # 获取用户所在的语音频道
        user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
        if not user_channels:
            await msg.reply('请先加入一个语音频道或提供频道ID后再使用点歌功能')
            return
        target_channel_id = user_channels[0].id

        # 获取当前活跃频道列表
        alive_data = await core.get_alive_channel_list()
        if 'error' in alive_data:
            await msg.reply(f"获取频道列表时发生错误: {alive_data['error']}")
            return

        # 检测机器人是否已在目标频道
        is_in_channel, error = core.is_bot_in_channel(alive_data, target_channel_id)
        if error:
            await msg.reply(f"检查频道状态时发生错误: {error}")
            return

        if is_in_channel:
            # 检查是否有正在进行的推流任务
            streamer = stream_tasks.get(target_channel_id)
            if streamer:
                await streamer.stop()  # 停止推流
                stream_tasks.pop(target_channel_id, None)  # 移除任务

            # 检查并取消之前的 monitor_stream 任务
            monitor_task = stream_monitor_tasks.get(target_channel_id)
            if monitor_task:
                monitor_task.cancel()
                stream_monitor_tasks.pop(target_channel_id, None)

            # 机器人已在目标频道，尝试离开
            leave_result = await core.leave_channel(target_channel_id)
            if 'error' in leave_result:
                await msg.reply(f"尝试离开频道时发生错误: {leave_result['error']}")
                return
            # 确认已离开
            alive_data = await core.get_alive_channel_list()
            is_in_channel, error = core.is_bot_in_channel(alive_data, target_channel_id)
            if is_in_channel:
                await msg.reply("离开频道失败，请稍后再试。")
                return
            elif error:
                await msg.reply(f"检查频道状态时发生错误: {error}")
                return

        # 尝试加入目标频道
        join_result = await core.join_channel(target_channel_id)
        if 'error' in join_result:
            await msg.reply(f"加入频道失败: {join_result['error']}\n请反馈开发者")
            return
        else:
            await msg.reply(f"加入频道成功！ID: {target_channel_id}")
            if target_channel_id not in keep_alive_tasks:
                task = asyncio.create_task(core.keep_channel_alive(target_channel_id))
                keep_alive_tasks[target_channel_id] = task

        # 参数处理与搜索
        keyword = " ".join(args)
        await msg.reply(f"正在搜索关键字: {keyword}")

        # 使用search_netease_music进行搜索，然后获取第一首歌曲信息
        try:
            search_results = await NeteaseAPI.search_netease_music(keyword)
            if search_results == "未找到相关音乐":
                await msg.reply("未找到相关音乐")
                # 尝试退出频道
                leave_result = await core.leave_channel(target_channel_id)
                if 'error' not in leave_result:
                    # 取消保持活跃任务
                    task = keep_alive_tasks.pop(target_channel_id, None)
                    if task:
                        task.cancel()
                return
                
            # 使用第一首搜索结果的歌曲下载
            first_song = search_results.split('\n')[0]
            await msg.reply(f"已找到歌曲：{first_song}，准备下载...")
            
            # 下载音乐
            songs = await NeteaseAPI.download_music(first_song)
        except Exception as e:
            await msg.reply(f"搜索或下载过程中发生错误: {e}")
            # 尝试退出频道
            leave_result = await core.leave_channel(target_channel_id)
            if 'error' not in leave_result:
                # 取消保持活跃任务
                task = keep_alive_tasks.pop(target_channel_id, None)
                if task:
                    task.cancel()
            return

        # 检查下载结果是否为错误消息
        if "error" in songs:
            await msg.reply(f"发生错误: {songs['error']}")
            # 尝试退出频道
            leave_result = await core.leave_channel(target_channel_id)
            if 'error' not in leave_result:
                # 取消保持活跃任务
                task = keep_alive_tasks.pop(target_channel_id, None)
                if task:
                    task.cancel()
            return

        # 如果下载成功，发送歌曲信息
        await msg.reply(
            f"已准备播放：\n{songs['song_name']} - {songs['artist_name']}({songs['album_name']})\n正在准备推流进程")
        audio_path = songs['file_name']
        await asyncio.sleep(3)

        # 使用 AudioStreamer 类进行推流
        streamer = core.AudioStreamer(audio_file_path=audio_path, connection_info=join_result)
        await streamer.start()

        # 将 streamer 实例存储在 stream_tasks 中
        stream_tasks[target_channel_id] = streamer

        # 创建一个后台任务来监测推流任务的完成
        async def monitor_stream():
            try:
                # 等待推流进程完成
                await streamer.process.wait()
            except asyncio.CancelledError:
                # 任务被取消，不需要执行退出逻辑
                return
            except Exception as error1:
                # 推流任务出现异常，已经在 AudioStreamer 中处理
                print(f"监测到推流任务异常: {error1}")
            finally:
                # 推流任务完成后，退出频道
                await asyncio.sleep(3)  # 等待3秒后退出频道
                leaveing_result = await core.leave_channel(target_channel_id)
                if 'error' not in leaveing_result:
                    # 取消保持活跃任务
                    task1 = keep_alive_tasks.pop(target_channel_id, None)
                    if task1:
                        task1.cancel()
                # await msg.reply(f"已完成推流并退出频道: {target_channel_id}")
                # 从 stream_tasks 中移除 streamer 实例
                stream_tasks.pop(target_channel_id, None)
                # 从 stream_monitor_tasks 中移除 monitor_stream 任务
                stream_monitor_tasks.pop(target_channel_id, None)

        # 创建并存储 monitor_stream 任务
        monitor_task = asyncio.create_task(monitor_stream())
        stream_monitor_tasks[target_channel_id] = monitor_task

    except asyncio.CancelledError:
        # 处理被取消的任务
        await msg.reply("任务已被取消。")
    except Exception as e:
        # 捕获其他预期外的异常
        await msg.reply(f"发生错误: {e}")
        # 尝试退出频道
        if 'target_channel_id' in locals():
            # noinspection PyUnboundLocalVariable
            leave_result = await core.leave_channel(target_channel_id)
            if 'error' not in leave_result:
                # 取消保持活跃任务
                task = keep_alive_tasks.pop(target_channel_id, None)
                if task:
                    task.cancel()


# endregion

# region 网易API测试部分
@bot.command(name="search", aliases=["搜索", "s"])
async def s1_command(msg: Message, *args):
    try:
        if not args:
            await msg.reply("参数缺失，请提供一个搜索关键字，例如：s1 周杰伦")
            return

        keyword = " ".join(args)  # 把空格后的所有内容拼接成一个字符串
        await msg.reply(f"正在搜索关键字: {keyword}")
        songs = await NeteaseAPI.search_netease_music(keyword)

        cm = CardMessage()
        c3 = Card(
            Module.Header('搜索结果如下：'))
        c3.append(
            Module.Container(Element.Image(src=msg.author.avatar)))
        c3.append(Module.Divider())  # 分割线
        text = f"{songs}"
        c3.append(Module.Section(Element.Text(text, Types.Text.KMD)))
        c3.append(Module.Context(
            Element.Text(f"{await local_hitokoto()}", Types.Text.KMD)  # 插入一言功能
        ))
        cm.append(c3)
        await msg.reply(cm)

    except Exception as e:
        await msg.reply(f"请检查API是否启动！若已经启动请报告开发者。 {e}")


# 下载（测试）
@bot.command(name='download', aliases=["d", "下载"])
async def download(msg: Message, *args):
    try:
        if not args:
            await msg.reply("参数缺失，请提供一个搜索关键字，例如：d 周杰伦")
            return
        else:
            # await core.qrcode_login()
            keyword = " ".join(args)  # 把空格后的所有内容拼接成一个字符串
            await msg.reply(f"正在搜索关键字: {keyword}")
            songs = await NeteaseAPI.download_music(keyword)
            if "error" in songs:
                await msg.reply(f"发生错误: {songs['error']}")
                return
            await msg.reply(f"歌曲：{songs['song_name']} - {songs['artist_name']}({songs['album_name']}) 下载完成\n"
                            f"URL地址:{songs['download_url']}\n"
                            f"路径:{songs['file_name']}")
    except Exception as e:
        await msg.reply(f"发生错误: {e}")


# qrcode login
@bot.command(name='login')
async def login(msg: Message):
    try:
        await msg.reply("正在登录，请开发者查看机器人后台")
        await NeteaseAPI.qrcode_login()
    except Exception as e:
        await msg.reply(f"发生错误: {e}")


# check CookieAlive
@bot.command(name='check')
async def check(msg: Message):
    try:
        a = await NeteaseAPI.ensure_logged_in()
        await msg.reply(a)
    except Exception as e:
        await msg.reply(f"发生错误: {e}")


# 对指定频道点歌
@bot.command(name="pc")
async def play_channel(msg: Message, song_name: str = "", channel_id: str = ""):
    if not song_name or not channel_id:
        await msg.reply("参数缺失，请提供歌名和频道ID，格式：pc \"歌名\" \"频道ID\"")
        return

    try:
        # 使用提供的频道ID
        target_channel_id = channel_id.strip()
        
        # 获取当前活跃频道列表
        alive_data = await core.get_alive_channel_list()
        if 'error' in alive_data:
            await msg.reply(f"获取频道列表时发生错误: {alive_data['error']}")
            return

        # 检测机器人是否已在目标频道
        is_in_channel, error = core.is_bot_in_channel(alive_data, target_channel_id)
        if error:
            await msg.reply(f"检查频道状态时发生错误: {error}")
            return

        if is_in_channel:
            # 检查是否有正在进行的推流任务
            streamer = stream_tasks.get(target_channel_id)
            if streamer:
                await streamer.stop()  # 停止推流
                stream_tasks.pop(target_channel_id, None)  # 移除任务

            # 检查并取消之前的 monitor_stream 任务
            monitor_task = stream_monitor_tasks.get(target_channel_id)
            if monitor_task:
                monitor_task.cancel()
                stream_monitor_tasks.pop(target_channel_id, None)

            # 机器人已在目标频道，尝试离开
            leave_result = await core.leave_channel(target_channel_id)
            if 'error' in leave_result:
                await msg.reply(f"尝试离开频道时发生错误: {leave_result['error']}")
                return
            # 确认已离开
            alive_data = await core.get_alive_channel_list()
            is_in_channel, error = core.is_bot_in_channel(alive_data, target_channel_id)
            if is_in_channel:
                await msg.reply("离开频道失败，请稍后再试。")
                return
            elif error:
                await msg.reply(f"检查频道状态时发生错误: {error}")
                return

        # 尝试加入目标频道
        join_result = await core.join_channel(target_channel_id)
        if 'error' in join_result:
            await msg.reply(f"加入频道失败: {join_result['error']}\n请反馈开发者")
            return
        else:
            await msg.reply(f"加入频道成功！ID: {target_channel_id}")
            if target_channel_id not in keep_alive_tasks:
                task = asyncio.create_task(core.keep_channel_alive(target_channel_id))
                keep_alive_tasks[target_channel_id] = task

        # 进行歌曲搜索
        await msg.reply(f"正在搜索歌曲: {song_name}")

        # 使用search_netease_music进行搜索，然后获取第一首歌曲信息
        try:
            search_results = await NeteaseAPI.search_netease_music(song_name)
            if search_results == "未找到相关音乐":
                await msg.reply("未找到相关音乐")
                # 尝试退出频道
                leave_result = await core.leave_channel(target_channel_id)
                if 'error' not in leave_result:
                    # 取消保持活跃任务
                    task = keep_alive_tasks.pop(target_channel_id, None)
                    if task:
                        task.cancel()
                return
                
            # 使用第一首搜索结果的歌曲下载
            first_song = search_results.split('\n')[0]
            await msg.reply(f"已找到歌曲：{first_song}，准备下载...")
            
            # 下载音乐
            songs = await NeteaseAPI.download_music(first_song)
        except Exception as e:
            await msg.reply(f"搜索或下载过程中发生错误: {e}")
            # 尝试退出频道
            leave_result = await core.leave_channel(target_channel_id)
            if 'error' not in leave_result:
                # 取消保持活跃任务
                task = keep_alive_tasks.pop(target_channel_id, None)
                if task:
                    task.cancel()
            return

        # 检查下载结果是否为错误消息
        if "error" in songs:
            await msg.reply(f"发生错误: {songs['error']}")
            # 尝试退出频道
            leave_result = await core.leave_channel(target_channel_id)
            if 'error' not in leave_result:
                # 取消保持活跃任务
                task = keep_alive_tasks.pop(target_channel_id, None)
                if task:
                    task.cancel()
            return

        # 如果下载成功，发送歌曲信息
        await msg.reply(
            f"已准备在频道 {target_channel_id} 播放：\n{songs['song_name']} - {songs['artist_name']}({songs['album_name']})\n正在准备推流进程")
        audio_path = songs['file_name']
        await asyncio.sleep(3)

        # 使用 AudioStreamer 类进行推流
        streamer = core.AudioStreamer(audio_file_path=audio_path, connection_info=join_result)
        await streamer.start()

        # 将 streamer 实例存储在 stream_tasks 中
        stream_tasks[target_channel_id] = streamer

        # 创建一个后台任务来监测推流任务的完成
        async def monitor_stream():
            try:
                # 等待推流进程完成
                await streamer.process.wait()
            except asyncio.CancelledError:
                # 任务被取消，不需要执行退出逻辑
                return
            except Exception as error1:
                # 推流任务出现异常，已经在 AudioStreamer 中处理
                print(f"监测到推流任务异常: {error1}")
            finally:
                # 推流任务完成后，退出频道
                await asyncio.sleep(3)  # 等待3秒后退出频道
                leaveing_result = await core.leave_channel(target_channel_id)
                if 'error' not in leaveing_result:
                    # 取消保持活跃任务
                    task1 = keep_alive_tasks.pop(target_channel_id, None)
                    if task1:
                        task1.cancel()
                # 从 stream_tasks 中移除 streamer 实例
                stream_tasks.pop(target_channel_id, None)
                # 从 stream_monitor_tasks 中移除 monitor_stream 任务
                stream_monitor_tasks.pop(target_channel_id, None)

        # 创建并存储 monitor_stream 任务
        monitor_task = asyncio.create_task(monitor_stream())
        stream_monitor_tasks[target_channel_id] = monitor_task

    except asyncio.CancelledError:
        # 处理被取消的任务
        await msg.reply("任务已被取消。")
    except Exception as e:
        # 捕获其他预期外的异常
        await msg.reply(f"发生错误: {e}")
        # 尝试退出频道
        if 'target_channel_id' in locals():
            # noinspection PyUnboundLocalVariable
            leave_result = await core.leave_channel(target_channel_id)
            if 'error' not in leave_result:
                # 取消保持活跃任务
                task = keep_alive_tasks.pop(target_channel_id, None)
                if task:
                    task.cancel()


# endregion

# region 检测功能
# 状态

'''
:return
'''

# endregion

# region 机器人运行主程序
# 机器人运行日志 监测运行状态
logging.basicConfig(level='INFO')
print("机器人已成功启动")
bot.command.update_prefixes("")  # 设置命令前缀为空
bot.run()
# endregion
