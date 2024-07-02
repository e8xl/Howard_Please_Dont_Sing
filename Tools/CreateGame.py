import json
import traceback

from khl import Bot, Message


def open_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        tmp = json.load(f)
    return tmp


# 打开config.json
config = open_file('../config/config.json')

# 初始化机器人
bot = Bot(token=config['token'])  # 默认采用 websocket


@bot.command(name='game-c')
async def game_create_cmd(msg: Message, name: str, icon=None):
    try:
        print("get /game-c cmd")
        # 处理 icon
        if icon != None and 'http' in icon:
            # 从命令行获取到的url，是kmd格式的，[url](url)，我们需要取出其中一个完整的url
            # 否则无法获取到图片，报错 Requesting 'POST game/create' failed with 40000: 无法获取文件信息
            index = icon.find('](')
            icon = icon[index + 2:-1]  # 取到完整url
            print(f"icon url:{icon}")
        # 创建游戏
        game = await bot.client.register_game(name, icon=icon)
        # 发送信息
        text = "创建游戏成功\n"
        text += "```\n"
        text += f"ID：{game.id}\n"
        text += f"名字：{game.name}\n"
        text += f"类型：{game.type}\n"
        text += "```\n"
        await msg.reply(text)
    except:
        print(traceback.format_exc())  # 如果出现异常，打印错误


bot.run()
