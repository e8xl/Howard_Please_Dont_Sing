import asyncio

import aiohttp


class VoiceClientError(Exception):
    """自定义异常类用于KookVoiceClient相关错误"""

    def __init__(self, message, code=None, data=None):
        super().__init__(message)
        self.code = code
        self.data = data

    def __str__(self):
        base = super().__str__()
        if self.code is not None:
            return f"[Error {self.code}] {base}"
        return base


class KookVoiceClient:
    """
    Kook App Voice API
    """

    def __init__(self, token, channel_id=None):
        self.token = token
        self.channel_id = channel_id
        self.base_url = "https://www.kookapp.cn/api/v3"
        self.headers = {
            "Authorization": f"Bot {self.token}"
        }
        self.session = aiohttp.ClientSession(headers=self.headers)

    async def join_channel(self, audio_ssrc="1111", audio_pt="111", rtcp_mux=True, password=None):
        """
        加入语音频道

        :param audio_ssrc: 传输的语音数据的ssrc
        :param audio_pt: 传输的语音数据的payload_type
        :param rtcp_mux: 是否将rtcp与rtp使用同一个端口进行传输
        :param password: 语音频道密码（如果需要）
        :return: 加入语音频道的相关数据
        :raises VoiceClientError: 如果请求失败或返回错误
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
            async with self.session.post(url, json=data, timeout=10) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if response_data['code'] == 0:
                        data = response_data['data']
                        # 转换rtcp_port为整数，如果存在且为字符串
                        if 'rtcp_port' in data and isinstance(data['rtcp_port'], str):
                            try:
                                data['rtcp_port'] = int(data['rtcp_port'])
                            except ValueError:
                                raise VoiceClientError("无效的 rtcp_port 格式", code=response_data.get('code'),
                                                       data=response_data)
                        return data
                    else:
                        raise VoiceClientError(
                            f"加入语音频道失败，错误信息: {response_data['message']}",
                            code=response_data.get('code'),
                            data=response_data
                        )
                else:
                    raise VoiceClientError(
                        f"加入语音频道请求失败，状态码: {response.status}",
                        code=response.status
                    )
        except aiohttp.ClientError as e:
            raise VoiceClientError(f"HTTP请求错误: {str(e)}") from e
        except asyncio.TimeoutError:
            raise VoiceClientError("HTTP请求超时")
        except Exception as e:
            raise VoiceClientError(f"加入语音频道异常: {str(e)}") from e

    async def list_channels(self):
        """
        获取机器人加入的语音频道列表

        :return: 频道列表数据
        :raises VoiceClientError: 如果请求失败或返回错误
        """
        url = f"{self.base_url}/voice/list"
        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if response_data['code'] == 0:
                        data = response_data['data']
                        # 可选：进一步处理数据，例如验证字段类型
                        return data
                    else:
                        raise VoiceClientError(
                            f"获取频道列表失败，错误信息: {response_data['message']}",
                            code=response_data.get('code'),
                            data=response_data
                        )
                else:
                    raise VoiceClientError(
                        f"获取频道列表请求失败，状态码: {response.status}",
                        code=response.status
                    )
        except aiohttp.ClientError as e:
            raise VoiceClientError(f"HTTP请求错误: {str(e)}") from e
        except asyncio.TimeoutError:
            raise VoiceClientError("HTTP请求超时")
        except Exception as e:
            raise VoiceClientError(f"获取频道列表异常: {str(e)}") from e

    async def leave_channel(self, channel_id=None):
        """
        离开语音频道

        :param channel_id: 需要离开的语音频道ID。如果未提供，将使用初始化时的channel_id
        :return: 操作结果数据
        :raises VoiceClientError: 如果请求失败或返回错误
        """
        url = f"{self.base_url}/voice/leave"
        # 使用提供的channel_id或默认的self.channel_id
        cid = channel_id if channel_id else self.channel_id
        data = {
            "channel_id": cid
        }
        try:
            async with self.session.post(url, json=data, timeout=10) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if response_data['code'] == 0:
                        return response_data['data']
                    else:
                        raise VoiceClientError(
                            f"离开语音频道失败，错误信息: {response_data['message']}",
                            code=response_data.get('code'),
                            data=response_data
                        )
                else:
                    raise VoiceClientError(
                        f"离开语音频道请求失败，状态码: {response.status}",
                        code=response.status
                    )
        except aiohttp.ClientError as e:
            raise VoiceClientError(f"HTTP请求错误: {str(e)}") from e
        except asyncio.TimeoutError:
            raise VoiceClientError("HTTP请求超时")
        except Exception as e:
            raise VoiceClientError(f"离开语音频道异常: {str(e)}") from e

    async def keep_alive(self, channel_id=None):
        """
        保持语音连接活跃

        :param channel_id: 需要保持活跃的语音频道ID。如果未提供，将使用初始化时的channel_id
        :return: 操作结果数据
        :raises VoiceClientError: 如果请求失败或返回错误
        """
        url = f"{self.base_url}/voice/keep-alive"
        # 使用提供的channel_id或默认的self.channel_id
        cid = channel_id if channel_id else self.channel_id
        data = {
            "channel_id": cid
        }
        try:
            async with self.session.post(url, json=data, timeout=10) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if response_data['code'] == 0:
                        return response_data['data']
                    else:
                        raise VoiceClientError(
                            f"保持语音连接活跃失败，错误信息: {response_data['message']}",
                            code=response_data.get('code'),
                            data=response_data
                        )
                else:
                    raise VoiceClientError(
                        f"保持语音连接活跃请求失败，状态码: {response.status}",
                        code=response.status
                    )
        except aiohttp.ClientError as e:
            raise VoiceClientError(f"HTTP请求错误: {str(e)}") from e
        except asyncio.TimeoutError:
            raise VoiceClientError("HTTP请求超时")
        except Exception as e:
            raise VoiceClientError(f"保持语音连接活跃异常: {str(e)}") from e

    async def close(self):
        """
        关闭HTTP会话
        """
        await self.session.close()
