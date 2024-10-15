# kook_voice_sdk.py

import asyncio
import logging
import sys
from asyncio import CancelledError

import aiohttp

# 配置日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class KookVoiceClient:
    """
    KOOK 语音客户端，用于处理语音频道的加入、离开、获取频道列表、保持连接活跃等操作
    """

    def __init__(self, token, channel_id):
        """
        初始化客户端
        :param token: 机器人 Token
        :param channel_id: 语音频道 ID
        """
        self.token = token
        self.channel_id = channel_id
        self.base_url = "https://www.kookapp.cn/api/v3"
        self.headers = {
            "Authorization": f"Bot {self.token}"
        }
        self.session = aiohttp.ClientSession(headers=self.headers)
        self.keep_alive_task = None  # 保持连接的任务
        self.closed = False  # 标记客户端是否已关闭
        self.stream_info = None  # 推流信息

    async def join_channel(self, audio_ssrc=1111, audio_pt=111, rtcp_mux=True, password=None):
        """
        加入语音频道，获取推流信息
        :param audio_ssrc: 传输的语音数据的 SSRC
        :param audio_pt: 传输的语音数据的 Payload Type
        :param rtcp_mux: 是否使用 RTCP Mux
        :param password: 如果频道需要密码，可以传入
        """
        url = f"{self.base_url}/voice/join"
        data = {
            "channel_id": self.channel_id,
            "audio_ssrc": audio_ssrc,
            "audio_pt": audio_pt,
            "rtcp_mux": rtcp_mux
        }
        if password:
            data["password"] = password

        try:
            async with self.session.post(url, json=data) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if response_data['code'] == 0:
                        self.stream_info = response_data['data']
                        logger.info("成功加入语音频道，推流信息已获取")
                        # 开始保持连接的任务
                        self.keep_alive_task = asyncio.create_task(self._keep_alive_loop())
                    else:
                        logger.error(f"加入语音频道失败，错误信息: {response_data['message']}")
                        await self.leave_channel()
                else:
                    logger.error(f"加入语音频道请求失败，状态码: {response.status}")
                    await self.leave_channel()
        except Exception as e:
            logger.exception(f"加入语音频道异常: {str(e)}")
            await self.leave_channel()

    async def leave_channel(self):
        """
        离开语音频道
        """
        if self.closed:
            return
        self.closed = True
        url = f"{self.base_url}/voice/leave"
        data = {
            "channel_id": self.channel_id
        }
        try:
            # 先取消保持连接的任务
            if self.keep_alive_task:
                self.keep_alive_task.cancel()

            async with self.session.post(url, json=data) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if response_data['code'] == 0:
                        logger.info("成功离开语音频道")
                    else:
                        logger.error(f"离开语音频道失败: {response_data['message']}")
                else:
                    logger.error(f"离开语音频道请求失败，状态码: {response.status}")
        except Exception as e:
            logger.exception(f"离开语音频道异常: {str(e)}")
        finally:
            await self.session.close()

    async def _keep_alive_loop(self):
        """
        保持语音连接活跃的循环任务
        """
        url = f"{self.base_url}/voice/keep-alive"
        data = {
            "channel_id": self.channel_id
        }
        try:
            while True:
                async with self.session.post(url, json=data) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        if response_data['code'] == 0:
                            logger.debug("发送心跳包成功")
                        else:
                            logger.error(f"发送心跳包失败: {response_data['message']}")
                    else:
                        logger.error(f"发送心跳包请求失败，状态码: {response.status}")
                await asyncio.sleep(45)  # 每隔45秒发送一次心跳包
        except CancelledError:
            logger.info("心跳任务已取消")
        except Exception as e:
            logger.exception(f"心跳任务异常: {str(e)}")
            await self.leave_channel()

    async def get_channel_list(self):
        """
        获取机器人加入的语音频道列表
        :return: 频道列表数据或 None
        """
        url = f"{self.base_url}/voice/list"
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if response_data['code'] == 0:
                        logger.info("成功获取语音频道列表")
                        return response_data['data']['items']
                    else:
                        logger.error(f"获取语音频道列表失败，错误信息: {response_data['message']}")
                else:
                    logger.error(f"获取语音频道列表请求失败，状态码: {response.status}")
        except Exception as e:
            logger.exception(f"获取语音频道列表异常: {str(e)}")
        return None

    def construct_stream_url(self):
        """
        构建推流地址，供其他程序（如 ffmpeg）使用
        :return: dict 包含推流地址和相关参数，或 None
        """
        if not self.stream_info:
            logger.error("未加入语音频道或推流信息未获取")
            return None

        ip = self.stream_info.get('ip')
        port = self.stream_info.get('port')
        rtcp_mux = self.stream_info.get('rtcp_mux', True)
        rtcp_port = self.stream_info.get('rtcp_port') if not rtcp_mux else None

        if rtcp_mux:
            stream_url = f"rtp://{ip}:{port}"
        else:
            stream_url = f"rtp://{ip}:{port}?rtcpport={rtcp_port}"

        stream_details = {
            "stream_url": stream_url,
            "ip": ip,
            "port": port,
            "rtcp_mux": rtcp_mux,
            "rtcp_port": rtcp_port,
            "bitrate": self.stream_info.get('bitrate'),
            "audio_ssrc": self.stream_info.get('audio_ssrc'),
            "audio_pt": self.stream_info.get('audio_pt')
        }

        logger.info(f"推流地址已构建: {stream_details}")
        return stream_details

    async def close(self):
        """
        关闭客户端，清理资源
        """
        await self.leave_channel()
