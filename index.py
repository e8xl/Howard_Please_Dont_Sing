import json
import logging
import random
import time
from datetime import datetime, timedelta

from khl import Bot, Message
from khl.card import Card, CardMessage, Element, Module, Types

from funnyAPI import we  # , get_hitokoto

from voiceAPI import Voice


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


# 主菜单
@bot.command(name='menu', aliases=['帮助', '菜单', "help"])
async def menu(msg: Message):
    cm = CardMessage()
    c3 = Card(
        Module.Header('你可以用下面这些指令呼叫我哦！'),
        Module.Context(
            Element.Text(f"开源代码见[Github](https://github.com/e8xl/8XL_kook_Music_bot),"
                         f"\n机器人启动时间: [{start_time}]\n"
                         f"娱乐部分参考项目[Ahri](https://github.com/Aewait/Valorant-Kook-Bot)"
                         f"丨音频部分[kook-voice-API](https://github.com/hank9999/kook-voice-API)"
                         f"\n点歌机器人参考[KO-ON](https://github.com/Gunale0926/KO-ON-Bot) 感恩奉献:)", Types.Text.KMD)))
    c3.append(Module.Section('「菜单」「帮助」都可以呼叫我\n'))
    c3.append(Module.Divider())  # 分割线
    c3.append(Module.Header('歌姬最重要的不是要唱歌吗??'))
    text = "「点歌 歌名」即可完成点歌任务"
    c3.append(Module.Divider())  # 分割线
    c3.append(Module.Header('和我玩小游戏吧~ '))
    text = "「/r 1 100」掷骰子1-100，范围可自主调节。可在末尾添加第三个参数实现同时掷多个骰子\n"
    text += "「/cd 秒数」倒计时，默认60秒\n"
    text += "「/we 城市」查询城市未来3天的天气情况\n"
    c3.append(Module.Section(Element.Text(text, Types.Text.KMD)))
    c3.append(Module.Divider())
    c3.append(
        Module.Section('帮我Github点个Star吧~', Element.Button('让我看看', 'https://www.8xl.icu', Types.Click.LINK)))
    c3.append(Module.Section('赞助一下吧~', Element.Button("赞助一下", 'https://afdian.net/a/888xl', Types.Click.LINK)))
    """
    一言会导致菜单响应速度过慢 参考服务器与API调用所影响 可以删除下面c3.append到KMD)))
    """
    '''
    c3.append(Module.Context(
        Element.Text(f"{await get_hitokoto()}", Types.Text.KMD)  # 插入一言功能
    ))
    '''
    cm.append(c3)
    await msg.reply(cm)


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
@bot.command()
async def cd(msg: Message, countdown_second: int = 60, *args):
    if args != ():
        await msg.reply(f"参数错误，cd命令只支持1个参数\n正确用法: `/countdown 120` 生成一个120s的倒计时")
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
@bot.command(name='we')
async def we_command(msg: Message, city: str = "err"):
    await we(msg, city)  # 调用we函数


# 点歌服务
@bot.command(name='点歌')
async def music(msg: Message, *args):
    await msg.reply(f"点歌功能暂未开放")


# 状态区域
bot.client.update_listening_music(f"MusicBot", "e1GhtXL")  # 设置机器人状态

# 机器人运行日志 监测运行状态
logging.basicConfig(level='INFO')
print("机器人已成功启动")
bot.command.update_prefixes("")
bot.run()
