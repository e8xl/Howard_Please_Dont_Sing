import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta

# 监测文件夹大小的阈值（字节）
AUDIO_LIB_SIZE_ALERT_THRESHOLD = 200 * 1024 * 1024  # 第一个数字为MB

from khl import Bot, Message
from khl.card import Card, CardMessage, Element, Module, Types

import NeteaseAPI
import core
from client_manager import keep_alive_tasks, stream_tasks, stream_monitor_tasks, playlist_tasks
from core import search_files
from funnyAPI import weather, local_hitokoto  # , get_hitokoto

# 创建logger
logger = logging.getLogger(__name__)


# 修改消息回调函数
async def message_callback(msg, message):
    """
    发送消息到用户
    
    :param msg: 原始的Message对象，用于回复
    :param message: 消息内容
    """
    try:
        # 直接回复原始消息
        await msg.reply(message)
        logger.info(f"发送消息: {message}")
    except Exception as e:
        logger.error(f"发送消息失败: {e}")


# 自动检查播放器状态的任务字典
auto_exit_tasks = {}


# 监控推流器状态，检查是否因为播放列表为空而退出
async def monitor_streamer_status(msg, channel_id):
    """
    监控推流器状态，如果因为播放列表为空而退出，则自动退出频道
    
    :param msg: 消息对象，用于回复用户
    :param channel_id: 频道ID
    """
    try:
        # 等待5秒钟，确保推流器状态已更新
        await asyncio.sleep(5)
        logger.info(f"开始监控频道 {channel_id} 的推流器状态")

        # 持续检查推流器状态
        while channel_id in playlist_tasks:
            enhanced_streamer = playlist_tasks[channel_id]

            # 检查推流器是否还存在
            if not hasattr(enhanced_streamer, 'streamer') or enhanced_streamer.streamer is None:
                logger.info(f"检测到频道 {channel_id} 的推流器已停止，准备退出频道")
                # 不能直接调用exit_command，需要手动执行退出逻辑
                try:
                    # 停止播放列表和推流任务
                    if channel_id in playlist_tasks:
                        enhanced_streamer = playlist_tasks.pop(channel_id, None)
                        if enhanced_streamer:
                            await enhanced_streamer.stop()

                    # 使用退出函数
                    leave_result = await core.leave_channel(channel_id)
                    if 'error' in leave_result:
                        # await msg.reply(f"退出频道失败: {leave_result['error']}")
                        logger.error(f"退出频道失败: {leave_result['error']}")
                    else:
                        # await msg.reply(f"已成功退出频道: {channel_id}")
                        logger.info(f"已成功退出频道: {channel_id}")
                except Exception as e:
                    logger.error(f"退出频道时发生错误: {e}")
                    # await msg.reply(f"退出频道时发生错误: {e}")
                finally:
                    # 取消保持活跃任务
                    task = keep_alive_tasks.pop(channel_id, None)
                    if task:
                        task.cancel()

                    # 清理所有相关任务和引用
                    stream_tasks.pop(channel_id, None)
                    stream_monitor_tasks.pop(channel_id, None)

                    # 取消自动监控任务
                    task = auto_exit_tasks.pop(channel_id, None)
                    if task:
                        task.cancel()
                break

            # 检查推流器是否因为播放列表为空而退出
            if hasattr(enhanced_streamer.streamer, 'exit_due_to_empty_playlist') and enhanced_streamer.streamer.exit_due_to_empty_playlist:
                # 推流器已设置自动退出标志
                logger.info(f"检测到频道 {channel_id} 的推流器设置了空列表退出标志，准备退出频道")

                # 确保用户收到通知
                try:
                    await msg.reply(f"播放列表为空，10秒后将自动退出频道。如需继续播放，请添加歌曲。")
                except Exception as e:
                    logger.error(f"通知用户退出频道失败: {e}")

                # 等待10秒给用户添加歌曲的机会，但分成多次短等待，每次检查播放列表
                empty_playlist = True
                for i in range(5):  # 分5次等待，每次2秒
                    logger.info(f"等待用户添加歌曲：第{i+1}次检查，剩余{10-i*2}秒")
                    await asyncio.sleep(2)

                    # 重新检查播放列表状态
                    if channel_id in playlist_tasks:
                        enhanced_streamer = playlist_tasks[channel_id]
                        songs_list = await enhanced_streamer.list_songs()
                        
                        # 如果用户已添加新歌
                        if songs_list:
                            # 重置退出标志
                            if hasattr(enhanced_streamer.streamer, 'exit_due_to_empty_playlist'):
                                enhanced_streamer.streamer.exit_due_to_empty_playlist = False
                                logger.info(f"用户已添加新歌，已取消退出频道 {channel_id}")
                                empty_playlist = False
                                break

                # 如果播放列表仍然为空，执行退出操作
                if empty_playlist and channel_id in playlist_tasks:
                    enhanced_streamer = playlist_tasks[channel_id]
                    songs_list = await enhanced_streamer.list_songs()
                    if not songs_list:
                        # 执行退出操作 - 不能直接调用exit_command，需要手动执行退出逻辑
                        try:
                            # 停止播放列表和推流任务
                            if channel_id in playlist_tasks:
                                enhanced_streamer = playlist_tasks.pop(channel_id, None)
                                if enhanced_streamer:
                                    await enhanced_streamer.stop()

                            # 使用退出函数
                            leave_result = await core.leave_channel(channel_id)
                            if 'error' in leave_result:
                                # await msg.reply(f"退出频道失败: {leave_result['error']}")
                                logger.error(f"退出频道失败: {leave_result['error']}")
                            else:
                                # await msg.reply(f"已成功退出频道: {channel_id}")
                                logger.info(f"已成功退出频道: {channel_id}")
                        except Exception as e:
                            logger.error(f"退出频道时发生错误: {e}")
                            # await msg.reply(f"退出频道时发生错误: {e}")
                        finally:
                            # 取消保持活跃任务
                            task = keep_alive_tasks.pop(channel_id, None)
                            if task:
                                task.cancel()

                            # 清理所有相关任务和引用
                            stream_tasks.pop(channel_id, None)
                            stream_monitor_tasks.pop(channel_id, None)

                            # 取消自动监控任务
                            task = auto_exit_tasks.pop(channel_id, None)
                            if task:
                                task.cancel()
                break

            # 等待2秒后再次检查
            await asyncio.sleep(2)

    except asyncio.CancelledError:
        logger.info(f"频道 {channel_id} 的监控任务被取消")
    except Exception as e:
        logger.error(f"监控频道 {channel_id} 时发生错误: {e}")


# 计算文件夹大小的函数
def get_folder_size(folder_path):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(folder_path):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            # 只计算文件的大小，跳过符号链接防止重复计算或无限循环
            if not os.path.islink(file_path):
                total_size += os.path.getsize(file_path)
    return total_size


# 检查 AudioLib 文件夹大小
def check_audio_lib_size():
    audio_lib_path = "./AudioLib"
    # 如果文件夹不存在，创建它
    if not os.path.exists(audio_lib_path):
        os.makedirs(audio_lib_path)
        print(f"已创建 {audio_lib_path} 文件夹")
        return

    # 计算文件夹大小
    folder_size = get_folder_size(audio_lib_path)
    # 转换为MB便于显示
    folder_size_mb = folder_size / (1024 * 1024)

    # 输出当前文件夹大小
    print(f"当前 AudioLib 文件夹大小: {folder_size_mb:.2f} MB")

    # 检查是否超过阈值
    if folder_size > AUDIO_LIB_SIZE_ALERT_THRESHOLD:
        print(
            f"⚠️ 警告：AudioLib 文件夹大小 ({folder_size_mb:.2f} MB) 已超过设定阈值 ({AUDIO_LIB_SIZE_ALERT_THRESHOLD / (1024 * 1024):.2f} MB)")
        print("请及时清理 AudioLib 文件夹，以免占用过多存储空间！")


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

# 检查并设置音量参数默认值
if 'ffmpge_volume' not in config or config['ffmpge_volume'] == "":
    print("未设置音量参数，设置默认值 0.8")
    config['ffmpge_volume'] = "0.8"
    # 将更新后的配置写回文件
    try:
        with open('./config/config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"写入配置文件时发生错误: {e}")

# 验证音量参数是否合法
try:
    volume = float(config['ffmpge_volume'])
    if volume > 2.0:
        print(f"警告：音量参数 {volume} 超过最大值 2.0，将设置为 2.0")
        config['ffmpge_volume'] = "2.0"
        # 将更新后的配置写回文件
        with open('./config/config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
except ValueError:
    print(f"警告：音量参数 {config['ffmpge_volume']} 不是有效的数值，将设置为默认值 0.8")
    config['ffmpge_volume'] = "0.8"
    # 将更新后的配置写回文件
    with open('./config/config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

# 初始化机器人
bot = Bot(token=config['token'])  # 默认采用 websocket
token = config['token']


def get_time():
    return time.strftime("%y-%m-%d %H:%M:%S", time.localtime())


start_time = get_time()


# 设置机器人游戏状态函数
@bot.on_startup
async def set_bot_game_status(_):
    try:
        # 启动时检查 AudioLib 文件夹大小
        check_audio_lib_size()

        await bot.client.update_playing_game(2128858)
        print("已成功设置机器人游戏状态")
    except Exception as e:
        print(f"设置机器人游戏状态时发生错误: {e}")


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
    text += "「点歌 https://music.163.com/song?id=xxx」可以通过歌曲链接点歌\n"
    text += "「点歌 https://music.163.com/dj?id=xxx」可以播放电台节目\n"
    text += "「pc \"歌名或网易云链接\" \"频道ID\"」指定频道点歌，支持歌曲和电台\n"
    text += "「列表」「歌单」查看当前播放列表\n"
    text += "「跳过」「下一首」跳过当前正在播放的歌曲\n"
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
    # 该命令不再需要设置游戏状态，因为在启动时已经设置
    # await bot.client.update_playing_game(2128858)


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
    await weather(msg, city)  # 调用we函数


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
        # 提取参数构建RTP地址
        ip = join_result.get('ip')
        port = join_result.get('port')
        rtcp_port = join_result.get('rtcp_port')
        # audio_ssrc = join_result.get('audio_ssrc')
        # audio_pt = join_result.get('audio_pt')

        # 构建RTP地址
        rtp_address = f"rtp://{ip}:{port}?rtcpport={rtcp_port}"

        await msg.reply(f"成功加入频道: {target_channel_id}\n{join_result}\n\nRTP地址: {rtp_address}")
        if target_channel_id not in keep_alive_tasks:
            task = asyncio.create_task(core.keep_channel_alive(target_channel_id))
            keep_alive_tasks[target_channel_id] = task


# noinspection PyUnresolvedReferences

@bot.command(name="exit", aliases=["leave", "退出"])
async def exit_command(msg: Message, *args):
    # 确定离开的频道
    if args:
        try:
            # 不做强制类型转换，直接使用字符串形式的ID
            target_channel_id = args[0]
        except ValueError:
            await msg.reply("提供的频道ID无效，请确保提供的是有效ID。")
            return
    else:
        # 获取用户当前所在的语音频道
        user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
        if not user_channels:
            await msg.reply('请先加入一个语音频道或提供频道ID后再使用退出功能')
            return
        target_channel_id = user_channels[0].id

    try:
        # 停止播放列表和推流任务
        if target_channel_id in playlist_tasks:
            enhanced_streamer = playlist_tasks.pop(target_channel_id, None)
            if enhanced_streamer:
                await enhanced_streamer.stop()

        # 使用退出函数
        leave_result = await core.leave_channel(target_channel_id)
        if 'error' in leave_result:
            await msg.reply(f"退出频道失败: {leave_result['error']}")
        else:
            # await msg.reply(f"已成功退出频道: {target_channel_id}")
            logger.info(f"已成功退出频道: {target_channel_id}")
    except Exception as e:
        logger.error(f"退出频道时发生错误: {e}")
        await msg.reply(f"退出频道时发生错误: {e}")
    finally:
        # 取消保持活跃任务
        task = keep_alive_tasks.pop(target_channel_id, None)
        if task:
            task.cancel()

        # 清理所有相关任务和引用
        stream_tasks.pop(target_channel_id, None)
        stream_monitor_tasks.pop(target_channel_id, None)

        # 取消自动监控任务
        task = auto_exit_tasks.pop(target_channel_id, None)
        if task:
            task.cancel()


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
        await msg.reply(
            "参数缺失，请提供一个搜索关键字或网易云音乐链接，例如：\n点歌 周杰伦\n点歌 https://music.163.com/song?id=123456\n点歌 https://music.163.com/dj?id=3068136069")
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

        # 检查是否已有播放列表管理器
        has_playlist = target_channel_id in playlist_tasks and playlist_tasks[target_channel_id] is not None

        if not is_in_channel:
            # 机器人未在频道中，需要加入频道
            join_result = await core.join_channel(target_channel_id)
            if 'error' in join_result:
                await msg.reply(f"加入频道失败: {join_result['error']}\n请反馈开发者")
                return
            else:
                # await msg.reply(f"加入频道成功！ID: {target_channel_id}")
                logger.info(f"加入频道成功！ID: {target_channel_id}")
                if target_channel_id not in keep_alive_tasks:
                    task = asyncio.create_task(core.keep_channel_alive(target_channel_id))
                    keep_alive_tasks[target_channel_id] = task

                # 创建并启动新的推流器，传入消息对象和消息回调函数
                enhanced_streamer = core.EnhancedAudioStreamer(
                    connection_info=join_result,
                    message_obj=msg,
                    message_callback=message_callback
                )
                success = await enhanced_streamer.start()
                if not success:
                    await msg.reply("启动推流器失败，请稍后再试")
                    # 尝试退出频道
                    leave_result = await core.leave_channel(target_channel_id)
                    if 'error' not in leave_result:
                        # 取消保持活跃任务
                        task = keep_alive_tasks.pop(target_channel_id, None)
                        if task:
                            task.cancel()
                    return

                # 存储推流器
                stream_tasks[target_channel_id] = enhanced_streamer
                playlist_tasks[target_channel_id] = enhanced_streamer

                # 创建监控任务
                if target_channel_id not in auto_exit_tasks:
                    # 确保监控任务能持续追踪推流器状态直到自动退出
                    logger.info(f"为频道 {target_channel_id} 创建监控任务")
                    task = asyncio.create_task(monitor_streamer_status(msg, target_channel_id))
                    auto_exit_tasks[target_channel_id] = task

        # 参数处理与搜索
        keyword = " ".join(args)

        # 检查是否是网易云音乐URL或电台节目URL
        import re

        # 检查是否是网易云音乐歌曲链接
        song_id_match = re.search(r'music\.163\.com/song\?id=(\d+)', keyword)

        # 检查是否是网易云电台节目链接
        dj_id_match = re.search(r'music\.163\.com/dj\?id=(\d+)', keyword)

        if dj_id_match:
            # 处理电台节目
            dj_id = dj_id_match.group(1)
            # await msg.reply(f"检测到网易云电台节目链接，正在获取电台ID: {dj_id}")
            logger.info(f"检测到网易云电台节目链接，正在获取电台ID: {dj_id}")
            songs = await NeteaseAPI.download_radio_program(dj_id)
        elif song_id_match:
            # 直接使用ID获取歌曲
            music_id = song_id_match.group(1)
            # await msg.reply(f"检测到网易云音乐链接，正在获取歌曲ID: {music_id}")
            logger.info(f"检测到网易云音乐链接，正在获取歌曲ID: {music_id}")
            songs = await NeteaseAPI.download_music_by_id(music_id)
        else:
            # 使用关键词搜索
            # await msg.reply(f"正在搜索关键字: {keyword}")
            logger.info(f"正在搜索关键字: {keyword}")
            # 使用search_netease_music进行搜索，然后获取第一首歌曲信息
            try:
                search_results = await NeteaseAPI.search_netease_music(keyword)
                if search_results == "未找到相关音乐":
                    await msg.reply("未找到相关音乐")
                    # 如果是新创建的频道且没有其他歌曲，则退出频道
                    if not has_playlist and target_channel_id in playlist_tasks:
                        enhanced_streamer = playlist_tasks[target_channel_id]
                        songs_list = await enhanced_streamer.list_songs()
                        if not songs_list:
                            await enhanced_streamer.stop()
                            leave_result = await core.leave_channel(target_channel_id)
                            if 'error' not in leave_result:
                                task = keep_alive_tasks.pop(target_channel_id, None)
                                if task:
                                    task.cancel()
                                playlist_tasks.pop(target_channel_id, None)
                                stream_tasks.pop(target_channel_id, None)
                    return

                # 使用第一首搜索结果的歌曲ID直接下载，避免再次搜索
                first_song = search_results["formatted_list"].split('\n')[0]
                first_song_id = search_results["first_song_id"]
                logger.info(f"已找到歌曲：{first_song}，准备下载 ID: {first_song_id}")

                # 使用ID直接下载，避免再次搜索
                songs = await NeteaseAPI.download_music_by_id(first_song_id)
            except Exception as e:
                error_msg = str(e)
                if NeteaseAPI.is_api_connection_error(error_msg):
                    await msg.reply(NeteaseAPI.get_api_error_message())
                else:
                    await msg.reply(f"请检查API是否启动！若已经启动请报告开发者。 {e}")

                # 如果是新创建的频道且没有其他歌曲，则退出频道
                if not has_playlist and target_channel_id in playlist_tasks:
                    enhanced_streamer = playlist_tasks[target_channel_id]
                    songs_list = await enhanced_streamer.list_songs()
                    if not songs_list:
                        await enhanced_streamer.stop()
                        leave_result = await core.leave_channel(target_channel_id)
                        if 'error' not in leave_result:
                            task = keep_alive_tasks.pop(target_channel_id, None)
                            if task:
                                task.cancel()
                            playlist_tasks.pop(target_channel_id, None)
                            stream_tasks.pop(target_channel_id, None)
                return

        # 检查下载结果是否为错误消息
        if "error" in songs:
            await msg.reply(f"发生错误: {songs['error']}")
            # 如果是新创建的频道且没有其他歌曲，则退出频道
            if not has_playlist and target_channel_id in playlist_tasks:
                enhanced_streamer = playlist_tasks[target_channel_id]
                songs_list = await enhanced_streamer.list_songs()
                if not songs_list:
                    await enhanced_streamer.stop()
                    leave_result = await core.leave_channel(target_channel_id)
                    if 'error' not in leave_result:
                        task = keep_alive_tasks.pop(target_channel_id, None)
                        if task:
                            task.cancel()
                        playlist_tasks.pop(target_channel_id, None)
                        stream_tasks.pop(target_channel_id, None)
            return

        # 如果下载成功，发送歌曲信息
        cache_status = "（使用本地缓存）" if songs.get("cached", False) else ""
        content_type = "电台节目" if songs.get("is_radio", False) else "歌曲"

        # 获取当前播放列表
        enhanced_streamer = playlist_tasks[target_channel_id]
        songs_before = await enhanced_streamer.list_songs()
        has_songs_before = len(songs_before) > 0

        # 将歌曲添加到播放列表
        audio_path = songs['file_name']
        is_first_song = await enhanced_streamer.add_song(audio_path, songs)

        # 如果推流器停止了但仍在字典中，确保它重新开始
        if hasattr(enhanced_streamer, 'streamer') and enhanced_streamer.streamer and not enhanced_streamer.streamer._running:
            logger.info(f"检测到推流器已停止但仍在字典中，尝试重新启动推流器")
            try:
                # 尝试重新启动音频循环
                enhanced_streamer.streamer._running = True
                enhanced_streamer.streamer.exit_due_to_empty_playlist = False  # 确保重置退出标志
                asyncio.create_task(enhanced_streamer.streamer._audio_loop())
                logger.info(f"已重新启动推流器的音频循环")
            except Exception as e:
                logger.error(f"重新启动推流器时出错: {e}")

        # 获取更新后的播放列表
        songs_after = await enhanced_streamer.list_songs()

        # 构建消息文本 - 只记录在日志中，不发送给用户
        # 修改判断逻辑：检查添加歌曲前是否已有歌曲，而不是依赖is_first_song
        if has_songs_before:  # 如果添加歌曲前就有其他歌曲，显示"已加入播放列表"
            log_message = f"已添加到播放列表{cache_status}：\n"
            user_message = f"已加入播放列表: {songs['song_name']} - {songs['artist_name']}"
        else:  # 如果添加前播放列表为空，显示"即将播放"
            log_message = f"已准备播放{cache_status}：\n"
            user_message = f"即将播放: {songs['song_name']} - {songs['artist_name']}"

        log_message += f"{content_type}：{songs['song_name']} - {songs['artist_name']}({songs['album_name']})"

        # 如果是电台，添加描述信息到日志
        if songs.get("is_radio", False) and songs.get("description"):
            # 截取描述的前100个字符，避免消息过长
            short_desc = songs["description"][:100] + "..." if len(songs["description"]) > 100 else songs["description"]
            log_message += f"\n简介：{short_desc}"

        # 记录完整的播放列表信息到日志
        if len(songs_after) > 1:
            log_message += f"\n\n当前播放列表共有 {len(songs_after)} 首歌曲"
            if len(songs_after) <= 5:  # 如果列表不太长，记录完整列表
                log_message += "\n播放列表："
                for song in songs_after:
                    log_message += f"\n- {song}"

        # 记录日志但不发送给用户
        logger.info(log_message)

        # 只向用户发送简化的消息
        await msg.reply(user_message)

        # 确保监控任务存在且正常运行
        if target_channel_id not in auto_exit_tasks or auto_exit_tasks[target_channel_id].done():
            logger.info(f"重新创建频道 {target_channel_id} 的监控任务")
            task = asyncio.create_task(monitor_streamer_status(msg, target_channel_id))
            auto_exit_tasks[target_channel_id] = task

    except asyncio.CancelledError:
        # 处理被取消的任务
        await msg.reply("任务已被取消。")
    except Exception as e:
        # 捕获其他预期外的异常
        error_msg = str(e)
        if NeteaseAPI.is_api_connection_error(error_msg):
            await msg.reply(NeteaseAPI.get_api_error_message())
        else:
            await msg.reply(f"发生错误: {e}")


# 添加一个查看当前播放列表的命令
@bot.command(name="list", aliases=["列表", "歌单"])
async def list_playlist(msg: Message):
    try:
        # 获取用户所在的语音频道
        user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
        if not user_channels:
            await msg.reply('请先加入一个语音频道后再使用此功能')
            return

        target_channel_id = user_channels[0].id

        # 检查是否有播放列表
        if target_channel_id not in playlist_tasks or playlist_tasks[target_channel_id] is None:
            await msg.reply('该频道没有活跃的播放列表')
            return

        # 获取播放列表
        enhanced_streamer = playlist_tasks[target_channel_id]
        songs_list = await enhanced_streamer.list_songs()

        if not songs_list:
            await msg.reply('播放列表为空')
            return

        # 构建消息
        message_text = "当前播放列表：\n"
        for song in songs_list:
            message_text += f"- {song}\n"

        await msg.reply(message_text)

    except Exception as e:
        await msg.reply(f"获取播放列表时发生错误: {e}")


# 添加一个跳过当前歌曲的命令
@bot.command(name="skip", aliases=["跳过", "下一首"])
async def skip_song(msg: Message):
    try:
        # 获取用户所在的语音频道
        user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
        if not user_channels:
            await msg.reply('请先加入一个语音频道后再使用此功能')
            return

        target_channel_id = user_channels[0].id

        # 检查是否有播放列表
        if target_channel_id not in playlist_tasks or playlist_tasks[target_channel_id] is None:
            await msg.reply('该频道没有活跃的播放列表')
            return

        # 跳过当前歌曲
        enhanced_streamer = playlist_tasks[target_channel_id]
        old, new = await enhanced_streamer.skip_current()

        if not old:
            await msg.reply('当前没有正在播放的歌曲')
            return

        # 获取真实的歌曲名称
        old_song_name = os.path.basename(old)
        new_song_name = os.path.basename(new) if new else None

        # 尝试从播放列表管理器获取歌曲信息
        playlist_manager = enhanced_streamer.playlist_manager

        # 获取旧歌曲信息
        if old in playlist_manager.songs_info:
            old_info = playlist_manager.songs_info[old]
            old_song_name = f"{old_info.get('song_name', '')} - {old_info.get('artist_name', '')}"

        # 获取新歌曲信息
        if new and new in playlist_manager.songs_info:
            new_info = playlist_manager.songs_info[new]
            new_song_name = f"{new_info.get('song_name', '')} - {new_info.get('artist_name', '')}"

            # 如果有下一首歌，将它添加到recently_added_songs集合中，避免重复通知
            playlist_manager.recently_added_songs.add(new)

        # 构建消息
        if new:
            # 只需显示即将播放的歌曲，不显示已跳过的歌曲
            await msg.reply(f'即将播放: {new_song_name}')
            # 记录完整信息到日志
            logger.info(f'已跳过: {old_song_name}\n即将播放: {new_song_name}')
        else:
            await msg.reply(f'已跳过: {old_song_name}\n播放列表已播放完毕')

    except Exception as e:
        await msg.reply(f"跳过歌曲时发生错误: {e}")


@bot.command(name="pc")
async def play_channel(msg: Message, song_name: str = "", channel_id: str = ""):
    if not song_name or not channel_id:
        await msg.reply("参数缺失，请提供歌名/URL和频道ID，格式：pc \"歌名或网易云链接\" \"频道ID\"")
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

        # 检查是否已有播放列表管理器
        has_playlist = target_channel_id in playlist_tasks and playlist_tasks[target_channel_id] is not None

        if not is_in_channel:
            # 机器人未在频道中，需要加入频道
            join_result = await core.join_channel(target_channel_id)
            if 'error' in join_result:
                await msg.reply(f"加入频道失败: {join_result['error']}\n请反馈开发者")
                return
            else:
                await msg.reply(f"加入频道成功！ID: {target_channel_id}")
                if target_channel_id not in keep_alive_tasks:
                    task = asyncio.create_task(core.keep_channel_alive(target_channel_id))
                    keep_alive_tasks[target_channel_id] = task

                # 创建并启动新的推流器，传入消息对象和消息回调函数
                enhanced_streamer = core.EnhancedAudioStreamer(
                    connection_info=join_result,
                    message_obj=msg,
                    message_callback=message_callback
                )
                success = await enhanced_streamer.start()
                if not success:
                    await msg.reply("启动推流器失败，请稍后再试")
                    # 尝试退出频道
                    leave_result = await core.leave_channel(target_channel_id)
                    if 'error' not in leave_result:
                        # 取消保持活跃任务
                        task = keep_alive_tasks.pop(target_channel_id, None)
                        if task:
                            task.cancel()
                    return

                # 存储推流器
                stream_tasks[target_channel_id] = enhanced_streamer
                playlist_tasks[target_channel_id] = enhanced_streamer

                # 创建监控任务
                if target_channel_id not in auto_exit_tasks:
                    # 确保监控任务能持续追踪推流器状态直到自动退出
                    logger.info(f"为频道 {target_channel_id} 创建监控任务")
                    task = asyncio.create_task(monitor_streamer_status(msg, target_channel_id))
                    auto_exit_tasks[target_channel_id] = task

        # 检查song_name是否是各种网易云音乐链接或ID
        import re

        # 检查是否是网易云音乐歌曲链接
        song_id_match = re.search(r'music\.163\.com/song\?id=(\d+)', song_name)

        # 检查是否是网易云电台节目链接
        dj_id_match = re.search(r'music\.163\.com/dj\?id=(\d+)', song_name)

        # 如果第一个参数是纯数字且长度不小于6位，也视为直接ID
        is_direct_id = song_name.isdigit() and len(song_name) >= 6

        if dj_id_match:
            # 处理电台节目
            dj_id = dj_id_match.group(1)
            await msg.reply(f"检测到网易云电台节目链接，正在获取电台ID: {dj_id}")
            songs = await NeteaseAPI.download_radio_program(dj_id)
        elif song_id_match or is_direct_id:
            # 直接使用ID获取歌曲
            if song_id_match:
                music_id = song_id_match.group(1)
                await msg.reply(f"检测到网易云音乐链接，正在获取歌曲ID: {music_id}")
            else:
                music_id = song_name
                await msg.reply(f"检测到直接使用歌曲ID: {music_id}")

            songs = await NeteaseAPI.download_music_by_id(music_id)
        else:
            # 进行歌曲搜索
            await msg.reply(f"正在搜索歌曲: {song_name}")

            # 使用search_netease_music进行搜索，然后获取第一首歌曲信息
            try:
                search_results = await NeteaseAPI.search_netease_music(song_name)
                if search_results == "未找到相关音乐":
                    await msg.reply("未找到相关音乐")
                    # 如果是新创建的频道且没有其他歌曲，则退出频道
                    if not has_playlist and target_channel_id in playlist_tasks:
                        enhanced_streamer = playlist_tasks[target_channel_id]
                        songs_list = await enhanced_streamer.list_songs()
                        if not songs_list:
                            await enhanced_streamer.stop()
                            leave_result = await core.leave_channel(target_channel_id)
                            if 'error' not in leave_result:
                                task = keep_alive_tasks.pop(target_channel_id, None)
                                if task:
                                    task.cancel()
                                playlist_tasks.pop(target_channel_id, None)
                                stream_tasks.pop(target_channel_id, None)
                    return

                # 使用第一首搜索结果的歌曲ID直接下载，避免再次搜索
                first_song = search_results["formatted_list"].split('\n')[0]
                first_song_id = search_results["first_song_id"]
                logger.info(f"已找到歌曲：{first_song}，准备下载 ID: {first_song_id}")

                # 使用ID直接下载，避免再次搜索
                songs = await NeteaseAPI.download_music_by_id(first_song_id)
            except Exception as e:
                error_msg = str(e)
                if NeteaseAPI.is_api_connection_error(error_msg):
                    await msg.reply(NeteaseAPI.get_api_error_message())
                else:
                    await msg.reply(f"请检查API是否启动！若已经启动请报告开发者。 {e}")

                # 如果是新创建的频道且没有其他歌曲，则退出频道
                if not has_playlist and target_channel_id in playlist_tasks:
                    enhanced_streamer = playlist_tasks[target_channel_id]
                    songs_list = await enhanced_streamer.list_songs()
                    if not songs_list:
                        await enhanced_streamer.stop()
                        leave_result = await core.leave_channel(target_channel_id)
                        if 'error' not in leave_result:
                            task = keep_alive_tasks.pop(target_channel_id, None)
                            if task:
                                task.cancel()
                            playlist_tasks.pop(target_channel_id, None)
                            stream_tasks.pop(target_channel_id, None)
                return

        # 检查下载结果是否为错误消息
        if "error" in songs:
            await msg.reply(f"发生错误: {songs['error']}")
            # 如果是新创建的频道且没有其他歌曲，则退出频道
            if not has_playlist and target_channel_id in playlist_tasks:
                enhanced_streamer = playlist_tasks[target_channel_id]
                songs_list = await enhanced_streamer.list_songs()
                if not songs_list:
                    await enhanced_streamer.stop()
                    leave_result = await core.leave_channel(target_channel_id)
                    if 'error' not in leave_result:
                        task = keep_alive_tasks.pop(target_channel_id, None)
                        if task:
                            task.cancel()
                        playlist_tasks.pop(target_channel_id, None)
                        stream_tasks.pop(target_channel_id, None)
            return

        # 如果下载成功，发送歌曲信息
        cache_status = "（使用本地缓存）" if songs.get("cached", False) else ""
        content_type = "电台节目" if songs.get("is_radio", False) else "歌曲"

        # 获取当前播放列表
        enhanced_streamer = playlist_tasks[target_channel_id]
        songs_before = await enhanced_streamer.list_songs()
        has_songs_before = len(songs_before) > 0

        # 将歌曲添加到播放列表
        audio_path = songs['file_name']
        is_first_song = await enhanced_streamer.add_song(audio_path, songs)

        # 如果推流器停止了但仍在字典中，确保它重新开始
        if hasattr(enhanced_streamer, 'streamer') and enhanced_streamer.streamer and not enhanced_streamer.streamer._running:
            logger.info(f"检测到推流器已停止但仍在字典中，尝试重新启动推流器")
            try:
                # 尝试重新启动音频循环
                enhanced_streamer.streamer._running = True
                enhanced_streamer.streamer.exit_due_to_empty_playlist = False  # 确保重置退出标志
                asyncio.create_task(enhanced_streamer.streamer._audio_loop())
                logger.info(f"已重新启动推流器的音频循环")
            except Exception as e:
                logger.error(f"重新启动推流器时出错: {e}")

        # 获取更新后的播放列表
        songs_after = await enhanced_streamer.list_songs()

        # 构建消息文本
        # 修改判断逻辑：检查添加歌曲前是否已有歌曲，而不是依赖is_first_song
        if has_songs_before:  # 如果添加前就有其他歌曲，显示"已加入播放列表"
            message_text = f"已添加到频道 {target_channel_id} 的播放列表{cache_status}：\n"
        else:  # 如果添加前播放列表为空，显示"即将播放"
            message_text = f"已准备在频道 {target_channel_id} 播放{cache_status}：\n"

        message_text += f"{content_type}：{songs['song_name']} - {songs['artist_name']}({songs['album_name']})"

        # 如果是电台，添加描述信息
        if songs.get("is_radio", False) and songs.get("description"):
            # 截取描述的前100个字符，避免消息过长
            short_desc = songs["description"][:100] + "..." if len(songs["description"]) > 100 else songs["description"]
            message_text += f"\n简介：{short_desc}"

        # 显示当前播放列表状态
        if len(songs_after) > 1:
            message_text += f"\n\n当前播放列表共有 {len(songs_after)} 首歌曲"
            if len(songs_after) <= 5:  # 如果列表不太长，显示完整列表
                message_text += "\n播放列表："
                for song in songs_after:
                    message_text += f"\n- {song}"

        await msg.reply(message_text)
        
        # 确保监控任务存在且正常运行
        if target_channel_id not in auto_exit_tasks or auto_exit_tasks[target_channel_id].done():
            logger.info(f"重新创建频道 {target_channel_id} 的监控任务")
            task = asyncio.create_task(monitor_streamer_status(msg, target_channel_id))
            auto_exit_tasks[target_channel_id] = task

    except asyncio.CancelledError:
        # 处理被取消的任务
        await msg.reply("任务已被取消。")
    except Exception as e:
        # 捕获其他预期外的异常
        error_msg = str(e)
        if NeteaseAPI.is_api_connection_error(error_msg):
            await msg.reply(NeteaseAPI.get_api_error_message())
        else:
            await msg.reply(f"发生错误: {e}")


# endregion

# region 网易API测试部分
@bot.command(name="search", aliases=["搜索", "s"])
async def s1_command(msg: Message, *args):
    """搜索歌曲"""
    keyword = " ".join(args).strip()
    if not keyword:
        await msg.reply("请提供要搜索的歌曲名")
        return

    # 使用NeteaseAPI进行搜索
    try:
        search_results = await NeteaseAPI.search_netease_music(keyword)
        if search_results == "未找到相关音乐":
            await msg.reply("未找到相关音乐")
            return
        
        # 只返回格式化的列表部分
        formatted_results = search_results["formatted_list"]
        # 分割获取第一首歌
        first_song = formatted_results.split('\n')[0]
        await msg.reply(f"搜索结果：\n{formatted_results}\n\n点歌指令示例：点歌 {first_song}")
    except Exception as e:
        error_msg = str(e)
        if NeteaseAPI.is_api_connection_error(error_msg):
            await msg.reply(NeteaseAPI.get_api_error_message())
        else:
            await msg.reply(f"搜索失败: {e}")


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
        error_msg = str(e)
        if NeteaseAPI.is_api_connection_error(error_msg):
            await msg.reply(NeteaseAPI.get_api_error_message())
        else:
            await msg.reply(f"发生错误: {e}")


# qrcode login
@bot.command(name='login')
async def login(msg: Message):
    try:
        await msg.reply("正在登录，请开发者查看机器人后台")
        await NeteaseAPI.qrcode_login()
    except Exception as e:
        error_msg = str(e)
        if NeteaseAPI.is_api_connection_error(error_msg):
            await msg.reply(NeteaseAPI.get_api_error_message())
        else:
            await msg.reply(f"发生错误: {e}")


# check CookieAlive
@bot.command(name='check')
async def check(msg: Message):
    try:
        a = await NeteaseAPI.ensure_logged_in()
        await msg.reply(a)
    except Exception as e:
        error_msg = str(e)
        if NeteaseAPI.is_api_connection_error(error_msg):
            await msg.reply(NeteaseAPI.get_api_error_message())
        else:
            await msg.reply(f"发生错误: {e}")


# endregion

# region 检测功能
# 状态

'''
:return
'''


# endregion
# 添加一个调整音量的命令
@bot.command(name="volume", aliases=["音量", "vol"])
async def set_volume(msg: Message, volume_str: str = None):
    if volume_str is None:
        # 显示当前音量
        try:
            volume = float(config['ffmpge_volume'])
            await msg.reply(f"当前音量：{volume}")
            return
        except ValueError:
            await msg.reply(f"当前音量设置无效：{config['ffmpge_volume']}，已重置为默认值 0.8")
            config['ffmpge_volume'] = "0.8"
            # 将更新后的配置写回文件
            with open('./config/config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return

    try:
        # 转换为浮点数
        volume = float(volume_str)

        # 验证音量是否在有效范围内
        if volume <= 0:
            await msg.reply(f"音量必须大于 0")
            return

        if volume > 2.0:
            await msg.reply(f"音量不能超过 2.0，已设置为最大值 2.0")
            volume = 2.0

        # 确保为浮点数格式
        volume_str = f"{volume:.1f}"

        # 更新配置
        config['ffmpge_volume'] = volume_str

        # 将更新后的配置写回文件
        with open('./config/config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        # 通知用户设置已保存，将在下次生效
        await msg.reply(f"音量已设置为：{volume_str}，将在下次机器人进入语音频道时生效")

    except ValueError:
        await msg.reply(f"无效的音量值：{volume_str}，请输入有效的数字")
        return


# region 机器人运行主程序
# 机器人运行日志 监测运行状态
logging.basicConfig(level='INFO')
print("机器人已成功启动")
bot.command.update_prefixes("")  # 设置命令前缀为空
bot.run()
# endregion
