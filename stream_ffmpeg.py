import asyncio
import os


# region 初始化设置

# 设置 ffmpeg 路径
def set_ffmpeg_path():
    ffmpeg_path = os.path.join(os.path.dirname(__file__), 'Tools', 'ffmpeg', 'bin', 'ffmpeg.exe')
    if not os.path.exists(ffmpeg_path):
        raise FileNotFoundError(f"未找到 ffmpeg.exe，请检查路径是否正确: {ffmpeg_path}")
    return ffmpeg_path


# 设置AudioLib文件夹路径
def set_audiolib_path():
    audiolib_path = os.path.join(os.path.dirname(__file__), 'AudioLib')
    if not os.path.exists(audiolib_path):
        os.makedirs(audiolib_path)
    return audiolib_path


# endregion

# region 音频处理
# 定义音频文件搜索函数
async def search_files(folder_path, search_keyword, file_extensions):
    """
    搜索指定文件夹中符合关键字和文件后缀的文件。

    :param folder_path: 要搜索的文件夹路径
    :param search_keyword: 文件名中包含的关键字（部分匹配）
    :param file_extensions: 文件后缀列表（如['.flac', '.mp3', '.wav']）
    :return: 符合条件的文件路径列表
    """
    result_files = []  # 用于存储符合条件的文件路径

    # 遍历文件夹及其子文件夹中的所有文件
    for root, dirs, files in os.walk(folder_path):
        # 遍历当前目录下的文件
        for music_name in files:
            # 检查文件名是否包含指定的关键字
            if search_keyword in music_name:
                # 检查文件后缀是否符合要求
                if any(music_name.endswith(extension) for extension in file_extensions):
                    # 将符合条件的文件完整路径添加到结果列表
                    result_files.append(os.path.join(root, music_name))

    return result_files  # 返回符合条件的文件列表


async def ffmpeg_stream(audio_file_path, ffmpeg_path):
    """
    使用 ffmpeg 推流音频文件。

    :param audio_file_path: 音频文件路径
    :param ffmpeg_path: ffmpeg.exe 文件路径
    """
    # 生成推流命令
    command = f"{ffmpeg_path} -re -i \"{audio_file_path}\" -f s16le -ar 48000 -ac 2 pipe:1"

    # 创建子进程
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    return process


if __name__ == "__main__":
    # 设置AudioLib文件夹路径
    audiolib_folder = set_audiolib_path()

    keyword = "孤勇者"
    file_extension = [".mp3", ".flac", ".wav"]

    # 搜索符合条件的文件
    matching_files = asyncio.run(search_files(audiolib_folder, keyword, file_extension))
    print(matching_files)
