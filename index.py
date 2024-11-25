import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Dict

from khl import Bot, Message
from khl.card import Card, CardMessage, Element, Module, Types

import core
from core import search_files
from funnyAPI import we, local_hitokoto  # , get_hitokoto

stream_tasks = {}


def open_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        tmp = json.load(f)
    return tmp


# 打开config.json
config = open_file('./config/config.json')

# 初始化机器人
bot = Bot(token=config['token'])  # 默认采用 websocket


def get_time():
    return time.strftime("%y-%m-%d %H:%M:%S", time.localtime())


start_time = get_time()

# region 逻辑函数部分
async def exit_channel(target_channel_id, msg=None):
    """
    退出指定的语音频道，并取消相关任务。

    :param target_channel_id: 目标语音频道的ID
    :param msg: 可选的消息对象，用于发送反馈
    """
    # 获取频道列表，以确保机器人不会尝试离开不存在的频道
    alive_data = await core.get_alive_channel_list()
    if 'error' in alive_data:
        if msg:
            await msg.reply(f"获取频道列表时发生错误: {alive_data['error']}")
        return

    # 检测机器人是否在目标频道中
    is_in_channel, error = core.is_bot_in_channel(alive_data, target_channel_id)
    if error:
        if msg:
            await msg.reply(f"检查频道状态时发生错误: {error}")
        return

    if not is_in_channel:
        if msg:
            await msg.reply(f"机器人未在频道 {target_channel_id} 中。")
        return

    # 如果有推流任务，取消它
    stream_task = stream_tasks.pop(target_channel_id, None)
    if stream_task:
        stream_task.cancel()
        try:
            await stream_task
            if msg:
                await msg.reply("推流任务已取消。")
        except asyncio.CancelledError:
            if msg:
                await msg.reply("推流任务已成功取消。")
        except Exception as e:
            if msg:
                await msg.reply(f"取消推流任务时发生错误: {e}")

    # 尝试离开目标频道
    leave_result = await core.leave_channel(target_channel_id)
    if 'error' in leave_result:
        if msg:
            await msg.reply(f"离开频道失败: {leave_result['error']}")
    else:
        if msg:
            await msg.reply(f"成功离开频道: {target_channel_id}")

        # 取消保持频道活跃的任务
        task = keep_alive_tasks.pop(target_channel_id, None)
        if task:
            task.cancel()
            try:
                await task
                print(f"保持频道 {target_channel_id} 活跃的任务已成功取消。")
            except asyncio.CancelledError:
                print(f"保持频道 {target_channel_id} 活跃的任务已成功取消。")
            except Exception as e:
                print(f"取消保持频道 {target_channel_id} 活跃任务时发生错误: {e}")
# endregion


# 主菜单
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
@bot.command()
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
@bot.command(name='we', aliases=["天气"])
async def we_command(msg: Message, city: str = "err"):
    await we(msg, city)  # 调用we函数


# region 点歌指令操作
keep_alive_tasks: Dict[str, asyncio.Task] = {}  # 用于存储频道保活任务


@bot.command(name="play")
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
            await msg.reply('请先加入一个语音频道或提供频道ID后再使用点歌功能')
            return
        target_channel_id = user_channels[0].id

    # 检测机器人是否在目标频道中
    is_in_channel, error = core.is_bot_in_channel(alive_data, target_channel_id)
    if error:
        await msg.reply(f"检查频道状态时发生错误: {error}")
        return

    if is_in_channel:
        # 机器人已在目标频道中，无需再次加入
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
# index.py

@bot.command(name="exit")
async def exit_command(msg: Message, *args):
    # 确定离开的频道
    if args:
        target_channel_id = args[0]
    else:
        # 获取用户当前所在的语音频道
        user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
        if not user_channels:
            await msg.reply('请先加入一个语音频道或提供频道ID后再使用退出功能')
            return
        target_channel_id = user_channels[0].id

    # 使用重构后的退出函数
    await exit_channel(target_channel_id, msg)



@bot.command(name="alive")
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


# index.py

@bot.command(name="test")
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
            await msg.reply(f"加入频道失败: {join_result['error']}")
            return
        else:
            await msg.reply(f"成功加入频道: {target_channel_id}\n{join_result}")
            if target_channel_id not in keep_alive_tasks:
                keep_alive_tasks[target_channel_id] = asyncio.create_task(core.keep_channel_alive(target_channel_id))

        # 参数处理与搜索
        keyword = " ".join(args)
        await msg.reply(f"正在搜索关键字: {keyword}")

        # 执行音乐搜索
        songs = await core.download_music(keyword)

        # 检查搜索结果是否为错误消息
        if isinstance(songs, str) and (
                songs.startswith("发生错误") or
                songs.startswith("未登录") or
                songs.startswith("未找到相关歌曲") or
                songs.startswith("无法获取下载链接")
        ):
            await msg.reply(f"搜索失败: {songs}")
            # 尝试退出频道
            await exit_channel(target_channel_id, msg)
            return

        # 如果搜索成功，发送歌曲信息
        await msg.reply(f"{songs}")
        audio_path = songs['file_name']
        stream_process = asyncio.create_task(core.stream_audio(audio_file_path=audio_path, connection_info=join_result))
        stream_tasks[target_channel_id] = stream_process

        # 创建一个后台任务来监测推流任务的完成
        async def monitor_stream():
            try:
                await stream_process
            except asyncio.CancelledError:
                # 任务被取消，不需要执行退出逻辑
                return
            except Exception as e:
                # 推流任务出现异常，已经在 stream_audio 中处理
                return e
            finally:
                # 推流任务完成后，退出频道
                await exit_channel(target_channel_id, msg)

        # noinspection PyAsyncCall
        asyncio.create_task(monitor_stream())

    except asyncio.CancelledError:
        # 处理被取消的任务
        await msg.reply("任务已被取消。")
    except Exception as e:
        # 捕获其他预期外的异常
        await msg.reply(f"发生错误: {e}")
        # 尝试退出频道
        if 'target_channel_id' in locals():
            # noinspection PyUnboundLocalVariable
            await exit_channel(target_channel_id, msg)



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
        songs = await core.search_netease_music(keyword)

        cm = CardMessage()
        c3 = Card(
            Module.Header('搜索结果如下：'))
        c3.append(
            Module.Container(Element.Image(src=msg.author.avatar)))
        c3.append(Module.Divider())  # 分割线
        text = f"{songs}"
        c3.append(Module.Section(Element.Text(text, Types.Text.KMD)))
        # c3.append(Module.Divider())  # 分割线
        # c3.append(
        #     Module.ActionGroup(
        #         Element.Button("下一页", value='按钮值1', click=Types.Click.RETURN_VAL, theme=Types.Theme.INFO),
        #         # Element.Button("按钮文字2", value='按钮值2', click=Types.Click.RETURN_VAL, theme=Types.Theme.DANGER),
        #         # Element.Button("按钮文字3", value='https://khl-py.eu.org/', click=Types.Click.LINK,
        #         #                theme=Types.Theme.SECONDARY)
        #     ))
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
            songs = await core.download_music(keyword)
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
        await core.qrcode_login()
    except Exception as e:
        await msg.reply(f"发生错误: {e}")


# check CookieAlive
@bot.command(name='check')
async def check(msg: Message):
    try:
        a = await core.ensure_logged_in()
        await msg.reply(a)
    except Exception as e:
        await msg.reply(f"发生错误: {e}")


# endregion

# region 检测功能
# 状态
@bot.command(name='状态')
async def status_command(msg: Message):
    if msg.ctx.guild:
        # 获取用户的服务器ID
        guild_id = msg.ctx.guild.id
        # 获取用户发送消息的文字频道ID
        channel_id = msg.ctx.channel.id
        # 尝试查找用户在语音频道中的状态
        voice_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
        if voice_channels:
            voice_channel_id = voice_channels[0].id
        else:
            voice_channel_id = "无"

        # 构造回复消息
        reply_message = f"您当前所在\n服务器ID: {guild_id}\n文字频道ID: {channel_id}\n语音频道ID: {voice_channel_id}"
        await msg.reply(reply_message)
    else:
        # 如果消息不在服务器中发送，给出提示
        await msg.reply("此命令只能在服务器内使用。")


# endregion

# 机器人运行日志 监测运行状态
logging.basicConfig(level='INFO')
print("机器人已成功启动")
bot.command.update_prefixes("")  # 设置命令前缀为空
bot.run()
