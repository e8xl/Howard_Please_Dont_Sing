import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta

# 监测文件夹大小的阈值（字节）
AUDIO_LIB_SIZE_ALERT_THRESHOLD = 200 * 1024 * 1024  # 第一个数字为MB

from khl import Bot, Message, EventTypes, Event
from khl.card import Card, CardMessage, Element, Module, Types

import NeteaseAPI
import core
from client_manager import keep_alive_tasks, stream_tasks, stream_monitor_tasks, playlist_tasks
from core import search_files
from funnyAPI import weather, local_hitokoto  # , get_hitokoto

# 创建logger
logger = logging.getLogger(__name__)

# 按钮点击的锁，防止连续点击
BUTTON_LOCKS = {}  # 格式: {'频道ID_操作类型': 时间戳}
BUTTON_COOLDOWN = 5  # 按钮冷却时间（秒）


# 按钮点击事件处理


# 修改消息回调函数
async def message_callback(msg, message):
    """
    发送消息到用户
    
    :param msg: 原始的Message对象，用于回复
    :param message: 消息内容
    """
    try:
        # 检查是否是过程性消息，如果是则只记录到日志中
        process_messages = [
            "正在获取歌单",
            "将导入全部歌曲",
            "正在从歌单",
            "共有",
            "首歌曲，将导入",
            "正在尝试加入",
            "机器人尚未加入频道",
            "这可能需要较长时间",
            "即将播放"
        ]

        # 检查消息是否包含任何过程性提示
        is_process_message = any(phrase in message for phrase in process_messages)

        if is_process_message:
            # 只记录到日志，不发送给用户
            logger.info(f"过程消息(未发送): {message}")
            return

        # 检查是否是播放消息
        if "正在播放:" in message or "正在播放：" in message:
            logger.info(f"收到播放消息: {message}")

            # 从消息对象中获取频道ID
            # 检查该消息是否与特定频道相关
            channel_id = None

            # 遍历所有播放器任务，找到与当前消息对象关联的频道
            for ch_id, enhanced_streamer in playlist_tasks.items():
                if hasattr(enhanced_streamer, 'message_obj') and enhanced_streamer.message_obj == msg:
                    channel_id = ch_id
                    logger.info(f"找到消息对象关联的频道: {channel_id}")
                    break

            if channel_id:
                # 调用播放卡片函数而不是发送简单文本
                logger.info(f"将为频道 {channel_id} 生成播放卡片")
                await playing_songcard(msg, channel_id, auto_mode=True)
                logger.info(f"已替换为播放卡片显示: {message}")
                return
            else:
                logger.warning(f"无法确定播放消息关联的频道，将使用普通文本消息")

        # 直接回复原始消息
        await msg.ctx.channel.send(message)
        logger.info(f"发送消息: {message}")
    except Exception as e:
        logger.error(f"发送消息失败: {e}")
        # 尝试直接发送错误文本
        try:
            await msg.ctx.channel.send(f"发送消息失败: {e}")
        except:
            pass


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

        # 初始化空播放列表标志
        empty_playlist = False

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
            if hasattr(enhanced_streamer.streamer,
                       'exit_due_to_empty_playlist') and enhanced_streamer.streamer.exit_due_to_empty_playlist:
                # 推流器已设置自动退出标志
                logger.info(f"检测到频道 {channel_id} 的推流器设置了空列表退出标志，准备退出频道")

                # 确保用户收到通知
                try:
                    await msg.ctx.channel.send(f"播放列表为空，10秒后将自动退出频道。如需继续播放，请添加歌曲。")
                except Exception as e:
                    logger.error(f"通知用户退出频道失败: {e}")

                # 等待10秒给用户添加歌曲的机会，但分成多次短等待，每次检查播放列表
                empty_playlist = True
                for i in range(5):  # 分5次等待，每次2秒
                    logger.info(f"等待用户添加歌曲：第{i + 1}次检查，剩余{10 - i * 2}秒")
                    await asyncio.sleep(2)

                    # 重新检查播放列表状态
                    # 确保playlist_tasks中仍然有这个频道
                    if channel_id not in playlist_tasks:
                        # 频道可能已经被其他地方清理了
                        logger.info(f"频道 {channel_id} 已不在播放列表任务中，终止监控")
                        empty_playlist = False  # 避免后续操作
                        break

                    enhanced_streamer = playlist_tasks[channel_id]
                    # 确认退出标志仍然为True
                    if hasattr(enhanced_streamer.streamer,
                               'exit_due_to_empty_playlist') and not enhanced_streamer.streamer.exit_due_to_empty_playlist:
                        logger.info(f"频道 {channel_id} 的退出标志已被取消，终止监控")
                        empty_playlist = False
                        break

                    # 检查是否有真实的新歌曲加入
                    has_real_songs = False

                    # 检查播放列表和下载队列是否确实有内容
                    if hasattr(enhanced_streamer.streamer, 'playlist_manager'):
                        has_current_song = enhanced_streamer.streamer.playlist_manager.current_song is not None
                        has_playlist_songs = len(enhanced_streamer.streamer.playlist_manager.playlist) > 0
                        has_download_queue = len(enhanced_streamer.streamer.playlist_manager.download_queue) > 0
                        has_temp_playlist = len(enhanced_streamer.streamer.playlist_manager.temp_playlist) > 0

                        has_real_songs = has_current_song or has_playlist_songs or has_download_queue or has_temp_playlist

                    # 仅当确实有歌曲时才取消退出
                    if has_real_songs:
                        # 重置退出标志
                        if hasattr(enhanced_streamer.streamer, 'exit_due_to_empty_playlist'):
                            enhanced_streamer.streamer.exit_due_to_empty_playlist = False
                            logger.info(f"用户已添加新歌，已取消退出频道 {channel_id}")
                            empty_playlist = False
                            break
                    else:
                        logger.info(f"播放列表表面上有歌曲，但实际检查发现没有真正的歌曲，继续退出流程")

                # 如果始终没有找到真实歌曲，强制执行退出，无需进一步检查
                if empty_playlist:
                    logger.info(f"等待结束，频道 {channel_id} 确认没有真实歌曲，强制执行退出操作")
                    try:
                        # 停止播放列表和推流任务
                        if channel_id in playlist_tasks:
                            enhanced_streamer = playlist_tasks.pop(channel_id, None)
                            if enhanced_streamer:
                                # 防止再次检查播放列表状态
                                if hasattr(enhanced_streamer.streamer, '_running'):
                                    enhanced_streamer.streamer._running = False
                                await enhanced_streamer.stop()

                        # 使用退出函数，强制执行离开
                        leave_result = await core.leave_channel(channel_id)
                        if 'error' in leave_result:
                            logger.error(f"退出频道失败: {leave_result['error']}")
                        else:
                            logger.info(f"已成功退出频道: {channel_id}")
                    except Exception as e:
                        logger.error(f"退出频道时发生错误: {e}")
                    finally:
                        # 清理所有相关任务和引用
                        task = keep_alive_tasks.pop(channel_id, None)
                        if task:
                            task.cancel()
                        stream_tasks.pop(channel_id, None)
                        stream_monitor_tasks.pop(channel_id, None)
                        task = auto_exit_tasks.pop(channel_id, None)
                        if task:
                            task.cancel()
                    # 直接退出循环，避免继续处理
                    break

            # 如果播放列表仍然为空，执行退出操作
            if empty_playlist and channel_id in playlist_tasks:
                enhanced_streamer = playlist_tasks[channel_id]
                songs_list = await enhanced_streamer.list_songs()

                # 再次进行全面检查，确保播放列表确实为空
                has_real_songs = False
                if hasattr(enhanced_streamer.streamer, 'playlist_manager'):
                    has_current_song = enhanced_streamer.streamer.playlist_manager.current_song is not None
                    has_playlist_songs = len(enhanced_streamer.streamer.playlist_manager.playlist) > 0
                    has_download_queue = len(enhanced_streamer.streamer.playlist_manager.download_queue) > 0
                    has_temp_playlist = len(enhanced_streamer.streamer.playlist_manager.temp_playlist) > 0

                    has_real_songs = has_current_song or has_playlist_songs or has_download_queue or has_temp_playlist

                # 有真实歌曲时，取消退出
                if has_real_songs:
                    logger.info(f"最终检查发现有歌曲，取消退出频道 {channel_id}")
                    if hasattr(enhanced_streamer.streamer, 'exit_due_to_empty_playlist'):
                        enhanced_streamer.streamer.exit_due_to_empty_playlist = False
                    # 重置empty_playlist标志
                    empty_playlist = False
                    continue

                # 以下为原有逻辑，只有确认没有任何歌曲后才会执行
                # 再次确认播放列表确实为空，避免误判断
                if not songs_list or len(songs_list) == 0:
                    # 最后确认下载队列也是空的
                    has_pending_downloads = False
                    if hasattr(enhanced_streamer.streamer, 'playlist_manager'):
                        has_pending_downloads = (
                                len(enhanced_streamer.streamer.playlist_manager.download_queue) > 0 or
                                len(enhanced_streamer.streamer.playlist_manager.temp_playlist) > 0
                        )

                    if not has_pending_downloads:
                        logger.info(f"最终确认：频道 {channel_id} 没有任何歌曲，执行退出操作")
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


# 格式化时间为MM:SS格式
def format_time(seconds):
    """
    将秒数格式化为MM:SS格式
    
    :param seconds: 秒数
    :return: 格式化后的时间字符串
    """
    if seconds is None:
        return "00:00"
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"


# 创建进度条
def get_progress_bar(current, total, bar_length=20):
    """
    创建文本进度条
    
    :param current: 当前位置
    :param total: 总时长
    :param bar_length: 进度条长度
    :return: 进度条文本
    """
    if total <= 0:
        return "▯" * bar_length

    progress = min(1.0, current / total)
    filled_length = int(bar_length * progress)

    # 创建进度条
    progress_bar = "▮" * filled_length + "▯" * (bar_length - filled_length)

    # 添加百分比
    percent = int(progress * 100)
    return f"{progress_bar} {percent}%"


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
@bot.on_event(EventTypes.MESSAGE_BTN_CLICK)
async def on_btn_clicked(_: Bot, e: Event):
    try:
        # 获取按钮值和用户信息
        value = e.body.get('value', '')
        user_id = e.body['user_info']['id']
        user_nickname = e.body['user_info']['nickname']

        # 获取目标频道ID (用于发送响应消息)
        target_id = e.body.get('target_id')

        if not target_id:
            logger.error("无法获取target_id，按钮处理失败")
            return

        logger.info(f"收到按钮点击：{value}，来自用户：{user_nickname}，响应频道：{target_id}")

        # 获取频道对象，而不是使用频道ID字符串
        try:
            # 从频道ID获取真正的Channel对象
            channel = await bot.client.fetch_public_channel(target_id)
            if not channel:
                logger.error(f"无法获取频道对象，ID: {target_id}")
                return
        except Exception as fetch_ex:
            logger.error(f"获取频道对象失败: {fetch_ex}")
            return

        # 按钮值格式：操作类型_频道ID
        parts = value.split('_', 1)
        action = parts[0]
        voice_channel_id = parts[1] if len(parts) > 1 else ""

        if not voice_channel_id:
            await channel.send("操作失败：未提供有效的语音频道ID")
            return

        # 检查该频道是否有活跃的播放列表
        if voice_channel_id not in playlist_tasks or playlist_tasks[voice_channel_id] is None:
            await channel.send("操作失败：找不到该频道的播放列表")
            return

        # 检查按钮锁
        lock_key = f"{voice_channel_id}_{action}"
        current_time = time.time()

        if lock_key in BUTTON_LOCKS:
            last_click_time = BUTTON_LOCKS[lock_key]
            time_diff = current_time - last_click_time

            if time_diff < BUTTON_COOLDOWN:
                # 在冷却期内，拒绝请求并提示用户
                remaining = round(BUTTON_COOLDOWN - time_diff, 1)
                await channel.send(f"操作过于频繁，请等待 {remaining} 秒后再试")
                return

        # 更新锁状态
        BUTTON_LOCKS[lock_key] = current_time

        # 处理按钮动作
        if action == "NEXT":
            # 处理"下一首"操作
            try:
                enhanced_streamer = playlist_tasks.get(voice_channel_id)
                if enhanced_streamer:
                    # 直接调用底层的skip_current方法
                    old, new = await enhanced_streamer.skip_current()

                    if new:
                        # 获取下一首歌曲信息
                        playlist_manager = enhanced_streamer.playlist_manager
                        new_title = os.path.basename(new)

                        if new in playlist_manager.songs_info:
                            new_info = playlist_manager.songs_info[new]
                            new_title = f"{new_info.get('song_name', '')} - {new_info.get('artist_name', '')}"

                        # 只发送简单的确认消息，不创建卡片
                        await channel.send(f"来自 {user_nickname} 的操作：已切换到下一首歌曲")

                        # 删除之前手动创建播放卡片的部分，让系统自动创建一个
                        # 因为当歌曲实际开始播放时，系统会自动发送播放通知
                    else:
                        await channel.send(f"来自 {user_nickname} 的操作：已跳过当前歌曲，播放列表已播放完毕")
                else:
                    await channel.send("操作失败：找不到该频道的播放器")
            except Exception as ex:
                logger.error(f"执行跳过操作时出错: {ex}")
                await channel.send(f"执行跳过操作时出错: {ex}")

                # 出错时释放锁
                BUTTON_LOCKS.pop(lock_key, None)

        elif action == "CLEAR":
            # 处理"清空播放列表"操作
            try:
                enhanced_streamer = playlist_tasks.get(voice_channel_id)
                if enhanced_streamer:
                    # 直接调用clear_playlist方法
                    count = await enhanced_streamer.clear_playlist()
                    if count > 0:
                        await channel.send(f"来自 {user_nickname} 的操作：已清空播放列表，移除了 {count} 首歌曲")
                    else:
                        await channel.send(f"来自 {user_nickname} 的操作：播放列表已经是空的")
                else:
                    await channel.send("操作失败：找不到该频道的播放器")
            except Exception as ex:
                logger.error(f"执行清空播放列表操作时出错: {ex}")
                await channel.send(f"执行清空播放列表操作时出错: {ex}")

                # 出错时释放锁
                BUTTON_LOCKS.pop(lock_key, None)

        elif action == "LOOP":
            # 处理"循环模式"操作
            try:
                enhanced_streamer = playlist_tasks.get(voice_channel_id)
                if enhanced_streamer:
                    # 获取当前模式
                    current_mode = await enhanced_streamer.get_play_mode()
                    next_mode = None

                    # 切换到下一个模式
                    if current_mode[0] == "sequential":
                        next_mode = "random"
                    elif current_mode[0] == "random":
                        next_mode = "single_loop"
                    elif current_mode[0] == "single_loop":
                        next_mode = "list_loop"
                    else:
                        next_mode = "sequential"

                    # 设置新模式
                    success = await enhanced_streamer.set_play_mode(next_mode)
                    if success:
                        new_mode_info = await enhanced_streamer.get_play_mode()
                        await channel.send(f"来自 {user_nickname} 的操作：已将播放模式切换为 {new_mode_info[1]}")
                    else:
                        await channel.send(f"来自 {user_nickname} 的操作：切换播放模式失败")
                else:
                    await channel.send("操作失败：找不到该频道的播放器")
            except Exception as ex:
                logger.error(f"执行切换播放模式操作时出错: {ex}")
                await channel.send(f"执行切换播放模式操作时出错: {ex}")

                # 出错时释放锁
                BUTTON_LOCKS.pop(lock_key, None)

        elif action == "EXIT":
            # 处理"退出频道"操作
            try:
                # 发送开始退出的消息
                await channel.send(f"来自 {user_nickname} 的操作：正在退出频道...")

                # 先取消所有相关任务
                keep_alive_task = keep_alive_tasks.pop(voice_channel_id, None)
                if keep_alive_task:
                    keep_alive_task.cancel()
                    logger.info(f"已取消频道 {voice_channel_id} 的保持活跃任务")

                stream_monitor_task = stream_monitor_tasks.pop(voice_channel_id, None)
                if stream_monitor_task:
                    stream_monitor_task.cancel()
                    logger.info(f"已取消频道 {voice_channel_id} 的流监控任务")

                auto_exit_task = auto_exit_tasks.pop(voice_channel_id, None)
                if auto_exit_task:
                    auto_exit_task.cancel()
                    logger.info(f"已取消频道 {voice_channel_id} 的自动退出任务")

                # 停止播放列表和推流
                enhanced_streamer = playlist_tasks.pop(voice_channel_id, None)
                if enhanced_streamer:
                    await enhanced_streamer.stop()
                    logger.info(f"已停止频道 {voice_channel_id} 的推流任务")

                # 清理其他任务
                stream_tasks.pop(voice_channel_id, None)

                # 最后调用core的leave_channel方法
                leave_result = await core.leave_channel(voice_channel_id)
                if 'error' in leave_result:
                    await channel.send(f"来自 {user_nickname} 的操作：退出频道失败: {leave_result['error']}")
                    logger.error(f"退出频道失败: {leave_result['error']}")
                else:
                    await channel.send(f"来自 {user_nickname} 的操作：已成功退出频道")
                    logger.info(f"已成功退出频道: {voice_channel_id}")

                # 退出成功后，移除该频道的所有锁
                for k in list(BUTTON_LOCKS.keys()):
                    if k.startswith(voice_channel_id):
                        BUTTON_LOCKS.pop(k, None)
            except Exception as ex:
                logger.error(f"执行退出频道操作时出错: {ex}")
                try:
                    await channel.send(f"执行退出频道操作时出错: {ex}")
                except:
                    logger.error("无法发送退出频道错误消息")

                # 出错时释放锁
                BUTTON_LOCKS.pop(lock_key, None)

    except Exception as ex:
        logger.error(f"处理按钮点击事件时出错: {ex}")
        # 尝试发送错误消息
        try:
            target_id = e.body.get('target_id')
            if target_id:
                # 尝试获取频道对象并发送消息
                try:
                    channel = await bot.client.fetch_public_channel(target_id)
                    if channel:
                        await channel.send(f"处理按钮点击事件时出错: {ex}")
                except Exception as channel_ex:
                    logger.error(f"获取频道对象或发送错误消息失败: {channel_ex}")
        except Exception as send_ex:
            logger.error(f"发送错误消息失败: {send_ex}")

        # 确保即使出错，也会释放所有相关的锁
        try:
            parts = value.split('_', 1)
            if len(parts) > 1:
                voice_channel_id = parts[1]
                action = parts[0]
                lock_key = f"{voice_channel_id}_{action}"
                BUTTON_LOCKS.pop(lock_key, None)
        except:
            pass


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
    # text += "「pc \"歌名或网易云链接\" \"频道ID\"」指定频道点歌，支持歌曲和电台\n"
    text += "「列表」「歌单」查看当前播放列表\n"
    text += "「跳过」「下一首」跳过当前正在播放的歌曲\n"
    text += "「搜索 歌名-歌手(可选)」搜索音乐\n"
    # text += "「下载 歌名-歌手(可选)」下载音乐（不要滥用球球了）\n"
    text += "「模式」「播放模式」更改播放模式，包括：顺序播放、随机播放、单曲循环、列表循环\n"
    text += "「当前模式」「查看模式」查看当前播放模式\n"
    # text += "「音量 [0.1-2.0]」调整音量大小\n"
    text += "「导入歌单 歌单URL [播放模式] [频道ID]」导入网易云音乐歌单，默认导入全部歌曲\n"
    text += "「删除 索引 [频道ID]」从播放列表中删除指定索引的歌曲\n"
    text += "「清空 [频道ID]」清空播放列表（不包括当前正在播放的歌曲）"
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
                             Element.Button("加入服务器", 'https://kook.vip/MnAt2Z', Types.Click.LINK)))
    """
    在线一言API会导致菜单响应速度过慢 参考服务器与API调用所影响 可以删除下面c3.append到KMD)))
    """
    '''
    c3.append(Module.Context(
        Element.Text(f"{await get_hitokoto()}", Types.Text.KMD)  # 插入一言功能
    ))
    '''

    c3.append(Module.Context(
        Element.Text(f"{await local_hitokoto()}", Types.Text.KMD)  # 插入本地一言功能
    ))

    cm.append(c3)
    await msg.reply(cm)


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
            await msg.reply(f"已成功退出频道")
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
                    message_callback=message_callback,
                    channel_id=target_channel_id
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
        if hasattr(enhanced_streamer,
                   'streamer') and enhanced_streamer.streamer and not enhanced_streamer.streamer._running:
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
        await msg.ctx.channel.send(user_message)

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
async def list_playlist(msg: Message, channel_id: str = ""):
    try:
        target_channel_id = None

        # 如果没有提供channel_id参数，则获取用户所在的语音频道
        if not channel_id:
            user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
            if not user_channels:
                await msg.reply('您当前不在任何语音频道中。请先加入一个语音频道，或提供频道ID作为参数，例如：`list 频道ID`')
                return
            target_channel_id = user_channels[0].id
        else:
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

        if not is_in_channel:
            await msg.reply(f"机器人当前不在频道 {target_channel_id} 中")
            return

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
        message_text = f"频道 {target_channel_id} 的当前播放列表：\n"
        for song in songs_list:
            message_text += f"- {song}\n"

        await msg.reply(message_text)

    except Exception as e:
        await msg.reply(f"获取播放列表时发生错误: {e}")


# 添加一个跳过当前歌曲的命令
@bot.command(name="skip", aliases=["跳过", "下一首"])
async def skip_song(msg: Message, channel_id: str = ""):
    """
    跳过当前歌曲
    
    :param msg: 消息对象
    :param channel_id: 频道ID，可选
    """
    try:
        # 确定目标频道
        target_channel_id = None

        # 如果没有提供channel_id参数，则获取用户所在的语音频道
        if not channel_id:
            user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
            if not user_channels:
                await msg.reply(
                    '您当前不在任何语音频道中。请先加入一个语音频道，或提供频道ID作为参数，例如：`skip 频道ID`')
                return
            target_channel_id = user_channels[0].id
        else:
            # 使用提供的频道ID
            target_channel_id = channel_id.strip()

        # 检查该频道是否有活跃的播放列表
        if target_channel_id not in playlist_tasks or playlist_tasks[target_channel_id] is None:
            await msg.reply(f'频道 {target_channel_id} 没有活跃的播放列表')
            return

        # 获取流媒体对象
        enhanced_streamer = playlist_tasks[target_channel_id]

        # 获取播放列表管理器
        playlist_manager = enhanced_streamer.playlist_manager

        # 获取当前播放的歌曲
        old_song = playlist_manager.current_song
        if not old_song:
            await msg.reply(f"频道 {target_channel_id} 没有正在播放的歌曲")
            return

        try:
            # 跳过当前歌曲
            old, new = await enhanced_streamer.skip_current()

            if old:
                # 获取旧歌曲的名称
                old_title = os.path.basename(old)

                # 尝试获取更好的歌曲名称（如果有）
                if old in playlist_manager.songs_info:
                    old_info = playlist_manager.songs_info[old]
                    old_title = f"{old_info.get('song_name', '')} - {old_info.get('artist_name', '')}"

                # 只发送已跳过的通知
                if new:
                    # 注意：这里不再发送"即将播放"的消息，让系统自动通知
                    await msg.reply(f"已跳过: {old_title}")
                else:
                    # 没有下一首歌了
                    await msg.reply(f"已跳过: {old_title}\n播放列表已播放完毕")
            else:
                # 跳过失败
                await msg.reply(f"频道 {target_channel_id} 跳过歌曲失败")
        except Exception as e:
            await msg.reply(f"跳过歌曲时发生错误: {e}")

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
                    message_callback=message_callback,
                    channel_id=target_channel_id
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

        # 使用统一的URL解析函数检查是否是网易云音乐链接
        parsed_url = NeteaseAPI.parse_music_url(song_name)
        url_type = parsed_url["type"]
        url_id = parsed_url["id"]

        if url_type == "dj":
            # 处理电台节目
            await msg.reply(f"检测到网易云电台节目链接，正在获取电台ID: {url_id}")
            songs = await NeteaseAPI.download_radio_program(url_id)
        elif url_type == "song" or url_type == "id":
            # 直接使用ID获取歌曲
            await msg.reply(f"检测到网易云音乐{url_type}，正在获取歌曲ID: {url_id}")
            songs = await NeteaseAPI.download_music_by_id(url_id)
        elif url_type in ["album", "djradio", "playlist"]:
            # 不支持的URL类型
            await msg.reply(f"PC命令不支持{url_type}类型的链接，请使用单曲或电台节目链接")
            return
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
        if hasattr(enhanced_streamer,
                   'streamer') and enhanced_streamer.streamer and not enhanced_streamer.streamer._running:
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

        # 创建卡片消息
        cm = CardMessage()
        card = Card(Module.Header('搜索结果如下：'))

        # 添加用户头像
        card.append(Module.Container(Element.Image(src=msg.author.avatar)))
        card.append(Module.Divider())  # 分割线

        # 获取搜索结果和第一首歌曲ID
        formatted_results = search_results["formatted_list"]
        first_song_id = search_results["first_song_id"]

        # 显示结果并美化格式
        songs_list = formatted_results.split('\n')
        first_song = songs_list[0] if songs_list else ""

        # 搜索结果部分
        card.append(Module.Section(Element.Text(f"**搜索关键词**: {keyword}", Types.Text.KMD)))
        card.append(Module.Section(Element.Text(formatted_results, Types.Text.KMD)))

        # 点歌提示
        if first_song:
            card.append(Module.Divider())
            card.append(Module.Section(Element.Text(f"**点歌指令示例**: 点歌 {first_song}", Types.Text.KMD)))

        # 添加一言
        card.append(Module.Context(Element.Text(f"{await local_hitokoto()}", Types.Text.KMD)))

        cm.append(card)
        await msg.reply(cm)
    except Exception as e:
        error_msg = str(e)
        if NeteaseAPI.is_api_connection_error(error_msg):
            await msg.reply(NeteaseAPI.get_api_error_message())
        else:
            await msg.reply(f"搜索失败: {e}")


@bot.command(name='download', aliases=["d", "下载"])
async def download(msg: Message, *args):
    if not args:
        await msg.reply("请提供关键词或ID")
        return

    try:
        # 组合关键词为字符串
        keyword = " ".join(args)

        # 如果是歌曲ID（纯数字）
        if keyword.isdigit():
            music_id = keyword
            # 直接使用ID获取歌曲URL
            song_url_info = await NeteaseAPI.get_song_url(music_id)

            if "error" in song_url_info:
                await msg.reply(f"获取歌曲URL出错: {song_url_info['error']}")
                return

            # 获取下载链接和其他信息
            song_url = song_url_info["song_url"]
            song_name = song_url_info["song_name"]
            artist_name = song_url_info["artist_name"]

            # 下载歌曲以便缓存本地（如果还未缓存）
            if not song_url_info["cached"]:
                songs = await NeteaseAPI.download_music_by_id(music_id)
                if "error" in songs:
                    await msg.reply(f"下载歌曲失败: {songs['error']}")
                    return

            # 构建消息
            await msg.reply(f"歌曲: {song_name} - {artist_name}\n下载链接: {song_url}")

        else:
            # 关键词搜索
            try:
                # 搜索网易云音乐
                search_result = await NeteaseAPI.search_netease_music(keyword)

                if isinstance(search_result, dict) and "formatted_list" in search_result:
                    # 获取第一首歌曲ID
                    first_song_id = search_result["first_song_id"]

                    # 获取歌曲直链
                    song_url_info = await NeteaseAPI.get_song_url(first_song_id)

                    if "error" in song_url_info:
                        await msg.reply(f"获取歌曲URL出错: {song_url_info['error']}")
                        return

                    # 获取下载链接和其他信息
                    song_url = song_url_info["song_url"]
                    song_name = song_url_info["song_name"]
                    artist_name = song_url_info["artist_name"]

                    # 下载歌曲以便缓存本地（如果还未缓存）
                    if not song_url_info["cached"]:
                        songs = await NeteaseAPI.download_music_by_id(first_song_id)
                        if "error" in songs:
                            await msg.reply(f"下载歌曲失败: {songs['error']}")
                            return

                    # 构建消息
                    search_list = search_result["formatted_list"]
                    await msg.reply(
                        f"🔍 搜索 \"{keyword}\" 结果:\n{search_list}\n\n已选择第一首: {song_name} - {artist_name}\n下载链接: {song_url}")
                else:
                    await msg.reply(f"搜索失败: {search_result}")
            except Exception as e:
                await msg.reply(f"搜索和下载过程中出错: {e}")
    except Exception as e:
        await msg.reply(f"处理下载请求时出错: {e}")


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


# region 播放模式切换
@bot.command(name="mode", aliases=["播放模式", "模式"])
async def set_play_mode(msg: Message, mode: str = None, channel_id: str = ""):
    """
    设置播放模式

    :param msg: 消息对象
    :param mode: 播放模式，可选值：顺序播放(sequential), 随机播放(random), 单曲循环(single), 列表循环(loop)
    :param channel_id: 频道ID，可选
    """
    try:
        # 如果没有提供mode参数，显示当前模式
        if not mode:
            await msg.reply(
                "请指定播放模式：\n- 顺序播放(sequential)\n- 随机播放(random)\n- 单曲循环(single)\n- 列表循环(loop)")
            return

        # 将中文模式名称转换为英文标识符
        mode_mapping = {
            "顺序播放": "sequential",
            "sequential": "sequential",
            "顺序": "sequential",
            "随机播放": "random",
            "random": "random",
            "随机": "random",
            "单曲循环": "single_loop",
            "single": "single_loop",
            "单曲": "single_loop",
            "列表循环": "list_loop",
            "loop": "list_loop",
            "循环": "list_loop"
        }

        # 转换模式名称
        if mode.lower() in mode_mapping:
            mode = mode_mapping[mode.lower()]
        else:
            await msg.reply(
                "无效的播放模式，可用模式：\n- 顺序播放(sequential)\n- 随机播放(random)\n- 单曲循环(single)\n- 列表循环(loop)")
            return

        # 确定目标频道
        target_channel_id = None

        # 如果没有提供channel_id参数，则获取用户所在的语音频道
        if not channel_id:
            user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
            if not user_channels:
                await msg.reply(
                    '您当前不在任何语音频道中。请先加入一个语音频道，或提供频道ID作为参数，例如：`mode random 频道ID`')
                return
            target_channel_id = user_channels[0].id
        else:
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

        if not is_in_channel:
            await msg.reply(f"机器人当前不在频道 {target_channel_id} 中")
            return

        # 检查该频道是否有活跃的播放列表
        if target_channel_id not in playlist_tasks or playlist_tasks[target_channel_id] is None:
            await msg.reply('该频道没有活跃的播放列表')
            return

        # 设置播放模式
        enhanced_streamer = playlist_tasks[target_channel_id]
        success = await enhanced_streamer.set_play_mode(mode)

        if success:
            # 获取当前播放模式的中文描述
            mode_info = await enhanced_streamer.get_play_mode()
            if mode_info:
                mode_name, mode_desc = mode_info
                await msg.reply(f"频道 {target_channel_id} 的播放模式已设置为: {mode_desc}")
            else:
                await msg.reply(f"频道 {target_channel_id} 的播放模式已设置为: {mode}")
        else:
            await msg.reply(f"设置播放模式失败")

    except Exception as e:
        await msg.reply(f"设置播放模式时发生错误: {e}")


@bot.command(name="currentmode", aliases=["当前模式", "查看模式"])
async def get_current_mode(msg: Message, channel_id: str = ""):
    """
    获取当前播放模式

    :param msg: 消息对象
    :param channel_id: 频道ID，可选
    """
    try:
        # 确定目标频道
        target_channel_id = None

        # 如果没有提供channel_id参数，则获取用户所在的语音频道
        if not channel_id:
            user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
            if not user_channels:
                await msg.reply(
                    '您当前不在任何语音频道中。请先加入一个语音频道，或提供频道ID作为参数，例如：`currentmode 频道ID`')
                return
            target_channel_id = user_channels[0].id
        else:
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

        if not is_in_channel:
            await msg.reply(f"机器人当前不在频道 {target_channel_id} 中")
            return

        # 检查该频道是否有活跃的播放列表
        if target_channel_id not in playlist_tasks or playlist_tasks[target_channel_id] is None:
            await msg.reply('该频道没有活跃的播放列表')
            return

        # 获取当前播放模式
        enhanced_streamer = playlist_tasks[target_channel_id]
        mode_info = await enhanced_streamer.get_play_mode()

        if mode_info:
            mode_name, mode_desc = mode_info
            await msg.reply(f"频道 {target_channel_id} 的当前播放模式为: {mode_desc}")
        else:
            await msg.reply(f"无法获取频道 {target_channel_id} 的播放模式")

    except Exception as e:
        await msg.reply(f"获取播放模式时发生错误: {e}")


@bot.command(name="progress", aliases=["进度", "播放进度"])
async def show_progress(msg: Message, channel_id: str = ""):
    """
    显示当前播放歌曲的进度
    
    :param msg: 消息对象
    :param channel_id: 频道ID，可选
    """
    try:
        # 确定目标频道
        target_channel_id = None

        # 如果没有提供channel_id参数，则获取用户所在的语音频道
        if not channel_id:
            user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
            if not user_channels:
                await msg.reply('请先加入一个语音频道，或提供频道ID作为参数，例如：`progress 频道ID`')
                return
            target_channel_id = user_channels[0].id
        else:
            # 使用提供的频道ID
            target_channel_id = channel_id.strip()

        # 获取活跃频道列表，检查机器人是否在该频道
        alive_data = await core.get_alive_channel_list()
        if 'error' in alive_data:
            await msg.reply(f"获取频道列表时发生错误: {alive_data['error']}")
            return

        # 检查机器人是否在频道中
        is_in_channel, error = core.is_bot_in_channel(alive_data, target_channel_id)
        if error:
            await msg.reply(f"检查频道状态时发生错误: {error}")
            return

        if not is_in_channel:
            await msg.reply(f"机器人不在该语音频道中。请使用 `join` 命令加入频道。")
            return

        # 获取对应频道的流媒体推送器
        if target_channel_id not in playlist_tasks:
            await msg.reply("当前没有正在播放的音乐。")
            return

        # 直接获取EnhancedAudioStreamer实例
        enhanced_streamer = playlist_tasks[target_channel_id]

        # 获取播放进度
        progress_info = await enhanced_streamer.get_current_progress()

        if not progress_info:
            await msg.reply("当前没有正在播放的音乐或无法获取进度信息。")
            return

        # 构建歌曲信息
        song_info = progress_info['song_info']
        song_name = song_info.get('song_name', '未知歌曲')
        artist_name = song_info.get('artist_name', '未知艺术家')

        # 构建进度条
        progress_percent = progress_info['progress_percent']
        bar_length = 20  # 进度条长度
        filled_length = int(bar_length * progress_percent / 100)
        progress_bar = '▮' * filled_length + '▯' * (bar_length - filled_length)

        # 构建回复消息
        reply_message = f"🎵 **{song_name}** - {artist_name}\n"
        reply_message += f"⏱️ {progress_info['formatted_position']} / {progress_info['formatted_duration']}\n"
        reply_message += f"📊 {progress_bar} {progress_percent:.1f}%"

        await msg.reply(reply_message)

    except Exception as e:
        await msg.reply(f"获取播放进度时发生错误: {e}")


@bot.command(name="import", aliases=["导入歌单", "歌单导入"])
async def import_playlist(msg: Message, playlist_url: str = "", play_mode: str = "", channel_id: str = ""):
    """
    导入网易云音乐歌单

    :param msg: 消息对象
    :param playlist_url: 歌单URL
    :param play_mode: 播放模式，可选值：顺序播放(sequential), 随机播放(random), 单曲循环(single), 列表循环(loop)
    :param channel_id: 频道ID，可选
    """
    try:
        # 检查是否提供了歌单URL
        if not playlist_url:
            await msg.reply(
                "请提供歌单URL，例如：`import https://music.163.com/playlist?id=13621716`\n可选参数：播放模式 [顺序/随机/单曲/循环]，例如：`import 歌单URL 随机`")
            return

        # 使用统一的URL解析函数检查是否是网易云音乐链接
        parsed_url = NeteaseAPI.parse_music_url(playlist_url)
        url_type = parsed_url["type"]
        url_id = parsed_url["id"]

        # 只允许playlist类型的链接
        if url_type != "playlist":
            await msg.reply(f"导入歌单命令只支持歌单类型的链接，当前链接类型为: {url_type}")
            return

        # 提取歌单ID
        playlist_id = url_id
        if not playlist_id:
            await msg.reply("无效的歌单URL，请提供正确的网易云音乐歌单链接")
            return

        # 处理播放模式参数
        mode = None
        if play_mode:
            # 将中文模式名称转换为英文标识符
            mode_mapping = {
                "顺序播放": "sequential",
                "sequential": "sequential",
                "顺序": "sequential",
                "随机播放": "random",
                "random": "random",
                "随机": "random",
                "单曲循环": "single_loop",
                "single": "single_loop",
                "单曲": "single_loop",
                "列表循环": "list_loop",
                "loop": "list_loop",
                "循环": "list_loop"
            }

            # 转换模式名称
            if play_mode.lower() in mode_mapping:
                mode = mode_mapping[play_mode.lower()]
            else:
                # 如果是数字或其他值，可能是旧的最大歌曲数参数，忽略它
                if not play_mode.isdigit() and play_mode.lower() != "all":
                    await msg.reply(
                        f"无效的播放模式: {play_mode}，将使用默认模式。\n可用模式：顺序播放、随机播放、单曲循环、列表循环")

        # 获取歌单详情（后台处理，不通知用户）
        playlist_detail = await NeteaseAPI.get_playlist_detail(playlist_id)
        if "error" in playlist_detail:
            await msg.reply(f"获取歌单信息失败: {playlist_detail['error']}")
            return

        # 获取歌单属性
        playlist_name = "未知歌单"
        playlist_creator = "未知用户"
        total_tracks = 0

        if "playlist" in playlist_detail:
            playlist = playlist_detail.get('playlist', {})
            playlist_name = playlist.get('name', '未知歌单')
            playlist_creator = playlist.get('creator', {}).get('nickname', '未知用户')
            total_tracks = playlist.get('trackCount', 0)

        # 默认导入全部歌曲
        max_songs_int = 0  # 0表示导入全部歌曲

        # 确定目标频道
        target_channel_id = None

        # 如果没有提供channel_id参数，则获取用户所在的语音频道
        if not channel_id:
            user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
            if not user_channels:
                await msg.reply(
                    f'歌单「{playlist_name}」导入失败：您当前不在任何语音频道中。请先加入一个语音频道，或提供频道ID作为参数，例如：`import 歌单URL 随机 频道ID`')
                return
            target_channel_id = user_channels[0].id
        else:
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

        # 如果机器人不在频道中，尝试加入频道
        if not is_in_channel:
            join_data = await core.join_channel(target_channel_id)
            if 'error' in join_data:
                await msg.reply(f"加入频道失败: {join_data['error']}")
                return

            # 初始化推流任务
            enhanced_streamer = core.EnhancedAudioStreamer(
                join_data,
                msg,
                message_callback,
                target_channel_id
            )

            # 启动推流服务
            success = await enhanced_streamer.start()
            if not success:
                await msg.reply(f"启动推流服务失败")
                # 离开频道
                await core.leave_channel(target_channel_id)
                return

            # 保存推流任务
            playlist_tasks[target_channel_id] = enhanced_streamer

            # 启动保持频道活跃的任务
            keep_alive_task = asyncio.create_task(core.keep_channel_alive(target_channel_id))
            keep_alive_tasks[target_channel_id] = keep_alive_task

            logger.info(f"已加入频道 {target_channel_id} 并启动推流服务")
            await msg.reply(f"已加入频道 {target_channel_id}，准备导入歌单「{playlist_name}」")

        # 检查该频道是否有活跃的播放列表
        if target_channel_id not in playlist_tasks or playlist_tasks[target_channel_id] is None:
            await msg.reply('无法获取频道的播放列表管理器')
            return

        # 获取推流器
        enhanced_streamer = playlist_tasks[target_channel_id]

        # 导入歌单
        result = await enhanced_streamer.import_playlist(playlist_id, max_songs_int, target_channel_id)

        if "error" in result:
            await msg.reply(f"导入歌单失败: {result['error']}")
            return

        # 如果设置了播放模式，应用它
        if mode:
            success = await enhanced_streamer.set_play_mode(mode)
            if success:
                # 获取当前播放模式的中文描述
                mode_info = await enhanced_streamer.get_play_mode()
                logger.info(f"已设置播放模式为: {mode_info[1] if mode_info else mode}")
            else:
                logger.error(f"设置播放模式失败: {mode}")

        # 构建成功消息
        playlist_name = result['name']
        creator = result['creator']
        total_tracks = result['total_tracks']
        imported_tracks = result['imported_tracks']

        description = result.get('description', '')
        if description and len(description) > 100:
            description = description[:100] + "..."

        message_text = f"已成功导入歌单：**{playlist_name}**\n"
        message_text += f"创建者：{creator}\n"
        message_text += f"共导入 {imported_tracks}/{total_tracks} 首歌曲\n"

        if description:
            message_text += f"简介：{description}\n"

        # 添加播放模式信息
        if mode:
            mode_info = await enhanced_streamer.get_play_mode()
            if mode_info:
                message_text += f"播放模式：{mode_info[1]}\n"

        message_text += "\n歌曲将按需下载并自动播放，可通过`list`命令查看当前播放列表"

        await msg.reply(message_text)

        # 创建或更新监控任务
        if target_channel_id not in auto_exit_tasks or auto_exit_tasks[target_channel_id].done():
            logger.info(f"重新创建频道 {target_channel_id} 的监控任务")
            task = asyncio.create_task(monitor_streamer_status(msg, target_channel_id))
            auto_exit_tasks[target_channel_id] = task

    except Exception as e:
        error_msg = str(e)
        if NeteaseAPI.is_api_connection_error(error_msg):
            await msg.reply(NeteaseAPI.get_api_error_message())
        else:
            await msg.reply(f"导入歌单时发生错误: {e}")


@bot.command(name="remove", aliases=["删除", "rm"])
async def remove_song(msg: Message, index: int = 0, channel_id: str = ""):
    """
    从播放列表中删除指定索引的歌曲

    :param msg: 消息对象
    :param index: 歌曲索引（从1开始）
    :param channel_id: 频道ID，可选
    """
    try:
        if index <= 0:
            await msg.reply("请提供要删除的歌曲索引（从1开始），例如：`remove 2`")
            return

        # 确定目标频道
        target_channel_id = None

        # 如果没有提供channel_id参数，则获取用户所在的语音频道
        if not channel_id:
            user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
            if not user_channels:
                await msg.reply(
                    '您当前不在任何语音频道中。请先加入一个语音频道，或提供频道ID作为参数，例如：`remove 2 频道ID`')
                return
            target_channel_id = user_channels[0].id
        else:
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

        if not is_in_channel:
            await msg.reply(f"机器人当前不在频道 {target_channel_id} 中")
            return

        # 检查该频道是否有活跃的播放列表
        if target_channel_id not in playlist_tasks or playlist_tasks[target_channel_id] is None:
            await msg.reply('该频道没有活跃的播放列表')
            return

        # 获取播放列表
        enhanced_streamer = playlist_tasks[target_channel_id]
        songs_list = await enhanced_streamer.list_songs()

        if not songs_list or len(songs_list) <= 1:  # 只有一首歌曲是当前播放，不能删除
            await msg.reply('播放列表为空或只有当前播放的歌曲，无法删除')
            return

        if index >= len(songs_list):
            await msg.reply(f'索引超出范围，播放列表中只有 {len(songs_list) - 1} 首待播放歌曲')
            return

        # 获取要删除的歌曲名称（显示用）
        song_to_remove = songs_list[index] if index < len(songs_list) else None

        # 删除歌曲
        success = await enhanced_streamer.remove_song(index)

        if success:
            await msg.reply(f"已从播放列表删除歌曲：{song_to_remove}")
        else:
            await msg.reply(f"删除歌曲失败")

    except Exception as e:
        await msg.reply(f"删除歌曲时发生错误: {e}")


@bot.command(name="clear", aliases=["清空", "清除"])
async def clear_playlist(msg: Message, channel_id: str = ""):
    """
    清空播放列表（不包括当前正在播放的歌曲）

    :param msg: 消息对象
    :param channel_id: 频道ID，可选
    """
    try:
        # 确定目标频道
        target_channel_id = None

        # 如果没有提供channel_id参数，则获取用户所在的语音频道
        if not channel_id:
            user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
            if not user_channels:
                await msg.reply(
                    '您当前不在任何语音频道中。请先加入一个语音频道，或提供频道ID作为参数，例如：`clear 频道ID`')
                return
            target_channel_id = user_channels[0].id
        else:
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

        if not is_in_channel:
            await msg.reply(f"机器人当前不在频道 {target_channel_id} 中")
            return

        # 检查该频道是否有活跃的播放列表
        if target_channel_id not in playlist_tasks or playlist_tasks[target_channel_id] is None:
            await msg.reply('该频道没有活跃的播放列表')
            return

        # 清空播放列表
        enhanced_streamer = playlist_tasks[target_channel_id]
        count = await enhanced_streamer.clear_playlist()

        if count > 0:
            await msg.reply(f"已清空播放列表，移除了 {count} 首歌曲")
        else:
            await msg.reply("播放列表已经是空的")

    except Exception as e:
        await msg.reply(f"清空播放列表时发生错误: {e}")


# endregion


async def playing_songcard(msg: Message, channel_id: str = "", auto_mode: bool = False):
    try:
        target_channel_id = None

        # 如果没有提供channel_id参数，则获取用户所在的语音频道
        if not channel_id:
            user_channels = await msg.ctx.guild.fetch_joined_channel(msg.author)
            if not user_channels:
                if not auto_mode:
                    await msg.reply(
                        '您当前不在任何语音频道中。请先加入一个语音频道，或提供频道ID作为参数，例如：`tc 频道ID`')
                return
            target_channel_id = user_channels[0].id
        else:
            # 使用提供的频道ID
            target_channel_id = channel_id.strip()

        # 检查该频道是否有活跃的播放列表
        if target_channel_id not in playlist_tasks or playlist_tasks[target_channel_id] is None:
            if not auto_mode:
                await msg.reply('该频道没有活跃的播放列表')
            logger.info(f"尝试为频道 {target_channel_id} 生成播放卡片，但没有活跃的播放列表")
            return

        # 获取播放列表管理器
        enhanced_streamer = playlist_tasks[target_channel_id]
        playlist_manager = enhanced_streamer.playlist_manager

        # 获取当前播放的歌曲信息
        current_song = playlist_manager.current_song
        if not current_song:
            if not auto_mode:
                await msg.reply('当前没有正在播放的歌曲')
            logger.info(f"尝试为频道 {target_channel_id} 生成播放卡片，但当前没有正在播放的歌曲")
            return

        # 获取歌曲详细信息
        song_info = None
        pic_url = "https://p2.music.126.net/6y-UleORITEDbvrOLV0Q8A==/5639395138885805.jpg"  # 默认封面
        song_url = "https://music.163.com/"  # 默认网址
        singer_url = "https://music.163.com/artist"  # 默认艺术家链接
        album_url = "https://music.163.com/album"  # 默认专辑链接
        song_name = os.path.basename(current_song)
        artist_name = "未知艺术家"
        album_name = "未知专辑"
        duration = 0
        audio_url = ""  # 音频直链

        # 尝试从文件名获取歌曲ID
        song_id = os.path.basename(current_song).split('.')[0]

        # 如果是网易云音乐ID，尝试通过API获取详细信息和音频URL
        if song_id.isdigit():
            try:
                # 导入NeteaseAPI
                import NeteaseAPI

                # 尝试获取歌曲URL和详情
                song_url_info = await NeteaseAPI.get_song_url(song_id)

                if "error" not in song_url_info:
                    # 获取直链URL
                    audio_url = song_url_info.get("song_url", "")

                    # 获取歌曲详情
                    song_detail = await NeteaseAPI.get_song_detail(song_id)

                    if "error" not in song_detail:
                        # 获取歌曲名称
                        song_name = song_detail.get('name', song_name)

                        # 获取艺术家信息
                        if song_detail.get('artists'):
                            artists = song_detail['artists']
                            artist_name = ", ".join(
                                [artist.get('name', '') for artist in artists if artist.get('name')])
                            # 获取第一个艺术家的ID用于链接
                            if artists and artists[0].get('id'):
                                artist_id = artists[0]['id']
                                singer_url = f"https://music.163.com/#/artist?id={artist_id}"

                        # 获取专辑信息
                        if song_detail.get('album'):
                            album = song_detail['album']
                            album_name = album.get('name', '未知专辑')
                            # 获取专辑ID用于链接
                            if album.get('id'):
                                album_id = album['id']
                                album_url = f"https://music.163.com/#/album?id={album_id}"
                            # 获取专辑封面
                            if album.get('picUrl'):
                                pic_url = album['picUrl']

                        # 获取歌曲时长
                        duration = song_detail.get('duration', 0)  # 已转换为秒

                        # 构建歌曲URL
                        song_url = f"https://music.163.com/#/song?id={song_id}"

                        print(f"从API获取到歌曲信息: {song_name} - {artist_name}")
                    else:
                        # 如果get_song_detail失败，但get_song_url成功，使用get_song_url的信息
                        song_name = song_url_info.get('song_name', song_name)
                        artist_name = song_url_info.get('artist_name', artist_name)
                        album_name = song_url_info.get('album_name', album_name)
                        pic_url = song_url_info.get('album_pic', pic_url)
                        song_url = f"https://music.163.com/#/song?id={song_id}"
                else:
                    print(f"获取歌曲URL失败: {song_url_info['error']}")
            except Exception as e:
                print(f"通过API获取歌曲详情时出错: {e}")
                # 如果API获取失败，回退到本地信息

        # 如果API获取失败或不是网易云ID，尝试从本地信息获取
        if not duration or duration == 0 or not artist_name or artist_name == "未知艺术家":
            # 尝试从playlist_manager中获取信息
            if current_song in playlist_manager.songs_info:
                local_info = playlist_manager.songs_info[current_song]

                # 只有在API没有获取到有效信息时才使用本地信息
                if not song_name or song_name == os.path.basename(current_song):
                    song_name = local_info.get('song_name', song_name)

                if artist_name == "未知艺术家":
                    artist_name = local_info.get('artist_name', artist_name)

                if album_name == "未知专辑":
                    album_name = local_info.get('album_name', album_name)

                # 设置封面图片URL，如果有的话
                if ('pic_url' in local_info and local_info['pic_url'] and
                        pic_url == "https://p2.music.126.net/6y-UleORITEDbvrOLV0Q8A==/5639395138885805.jpg"):
                    pic_url = local_info['pic_url']
            else:
                # 使用ffprobe获取基本信息
                info = playlist_manager.get_song_info(current_song)
                if not song_name or song_name == os.path.basename(current_song):
                    song_name = info['title']

                # 如果标题包含分隔符，尝试解析艺术家
                if " - " in song_name and artist_name == "未知艺术家":
                    parts = song_name.split(" - ", 1)
                    song_name = parts[0]
                    artist_name = parts[1]

        # 获取歌曲时长（如果之前未获取）
        if not duration or duration == 0:
            duration = playlist_manager.get_song_duration(current_song)
            if duration <= 0:
                duration = 180  # 默认3分钟

        # 获取当前播放进度
        progress_info = await enhanced_streamer.get_current_progress()
        current_position = 0
        if progress_info:
            current_position = progress_info['current_position']

        # 计算剩余时间
        remaining_time = max(0, duration - current_position)

        # 创建卡片
        cm = CardMessage()
        c3 = Card(
            Module.Header("正在播放： " + song_name),
            Module.Context(
                Element.Text(
                    "歌手： [" + artist_name + "](" + singer_url +
                    ")  — 专辑： [" + album_name + "](" + album_url + ")",
                    Types.Text.KMD)),
            # 添加音频模块，如果有直链就使用，否则只显示信息
            Module.File(Types.File.AUDIO,
                        src=audio_url,  # 如果获取到了直链就使用，否则为空
                        title=song_name,
                        cover=pic_url),
            # # 添加当前播放进度信息
            # Module.Section(
            #     Element.Text(f"播放进度：{format_time(current_position)} / {format_time(duration)}", Types.Text.KMD)
            # ),
            # # 添加进度条
            # Module.Section(
            #     Element.Text(get_progress_bar(current_position, duration), Types.Text.KMD)
            # ),
            # 使用剩余时间创建倒计时，而不是总时长
            Module.Countdown(datetime.now() +
                             timedelta(seconds=int(remaining_time)),
                             mode=Types.CountdownMode.SECOND),
            Module.Divider(),
            Module.Context(
                Element.Image(
                    src=
                    "https://img.kookapp.cn/assets/2022-05/UmCnhm4mlt016016.png"
                ),
                Element.Text("网易云音乐  [在网页查看](" + song_url + ")",
                             Types.Text.KMD)),
            Module.ActionGroup(
                Element.Button('下一首', f'NEXT_{target_channel_id}', Types.Click.RETURN_VAL),
                Element.Button('清空歌单', f'CLEAR_{target_channel_id}', Types.Click.RETURN_VAL),
                Element.Button('循环模式', f'LOOP_{target_channel_id}', Types.Click.RETURN_VAL),
                Element.Button('退出频道', f'EXIT_{target_channel_id}', Types.Click.RETURN_VAL)),

            Module.Divider(),
            Module.Section(
                Element.Text("👈点歌用户", type=Types.Text.KMD),
                Element.Image(src=msg.author.avatar, size=Types.Size.SM, circle=True)

            ),
            color="#6AC629")
        c3.append(Module.Context(
            Element.Text(f"{await local_hitokoto()}", Types.Text.KMD)  # 插入本地一言功能
        ))
        cm.append(c3)
        await msg.ctx.channel.send(cm)
    except Exception as e:
        error_msg = f"生成播放卡片时发生错误: {e}"
        logger.error(error_msg)
        if not auto_mode:
            await msg.reply(error_msg)


# region 测试

@bot.command(name='tc', aliases=['testcard'])
async def test_card(msg: Message, channel_id: str = ""):
    await playing_songcard(msg, channel_id)


# endregion

# region 机器人运行主程序
# 机器人运行日志 监测运行状态
logging.basicConfig(level='INFO')
print("机器人已成功启动")
bot.command.update_prefixes("")  # 设置命令前缀为空
bot.run()
# endregion
