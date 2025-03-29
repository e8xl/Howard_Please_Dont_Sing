import asyncio
import logging

from VoiceAPI import KookVoiceClient
from StreamTools.ffmpeg_stream_tool import FFmpegPipeStreamer, PlaylistManager

# 设置日志
logger = logging.getLogger(__name__)

# 全局字典来管理客户端实例
clients = {}
clients_lock = asyncio.Lock()

# 全局字典来管理保持活跃的任务
keep_alive_tasks = {}

# 全局字典来管理推流任务
stream_tasks = {}
stream_monitor_tasks = {}

# 新增：全局字典来管理播放列表任务
playlist_tasks = {}
playlist_managers = {}


async def get_client(channel_id, token):
    """
    获取或创建一个频道的客户端实例
    
    :param channel_id: 频道ID
    :param token: Kook API令牌
    :return: KookVoiceClient实例
    """
    async with clients_lock:
        try:
            if channel_id in clients:
                # 检查客户端是否仍然有效
                client = clients[channel_id]
                # 简单测试客户端是否仍可用
                try:
                    # 尝试获取频道列表，如果成功说明客户端仍然有效
                    list_data = await client.list_channels()
                    if 'error' in list_data:
                        logger.warning(f"客户端测试失败，创建新客户端: {list_data.get('error')}")
                        raise Exception("客户端测试失败")
                    return client
                except Exception as e:
                    logger.warning(f"客户端似乎无效，创建新客户端: {e}")
                    # 客户端无效，创建新的
                    await client.close()
                    client = KookVoiceClient(token, channel_id)
                    clients[channel_id] = client
                    logger.info(f"为频道 {channel_id} 重新创建了客户端")
                    return client
            else:
                # 创建新客户端
                client = KookVoiceClient(token, channel_id)
                clients[channel_id] = client
                logger.info(f"为频道 {channel_id} 创建了新客户端")
                return client
        except Exception as e:
            logger.error(f"获取客户端时发生错误: {e}")
            # 出错时创建新客户端并返回
            client = KookVoiceClient(token, channel_id)
            clients[channel_id] = client
            return client


async def remove_client(channel_id):
    """
    移除并关闭指定频道的客户端
    
    :param channel_id: 频道ID
    """
    async with clients_lock:
        client = clients.pop(channel_id, None)
        if client:
            try:
                await client.close()
                logger.info(f"已关闭频道 {channel_id} 的客户端")
            except Exception as e:
                logger.error(f"关闭频道 {channel_id} 的客户端时发生错误: {e}")
