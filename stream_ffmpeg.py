import asyncio

from core import stream_audio

asyncio.run(stream_audio(audio_file_path=r"D:\Acode\PythonProject\KookBot\HowardPDSing\AudioLib\64093.mp3",
                         connection_info={'ip': '127.0.0.1', 'port': 6666, 'rtcp_port': 6666,
                                          'audio_ssrc': 1111, 'audio_pt': 111, 'bitrate': 128000, 'rtcp_mux': True}))
