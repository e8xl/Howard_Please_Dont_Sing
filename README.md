# Howard Please Don't Sing
8XL_Kook_Music_bot<br>
About KookAPP Music BOT from [khl.py](https://github.com/TWT233/khl.py)
***
## 部分娱乐功能参照并修改自[Kook-Valorant-Bot](https://github.com/Valorant-Shop-CN/Kook-Valorant-Bot) <br>机器人功能主体来自[khl.py](https://github.com/TWT233/khl.py)
### 点歌部分参考[KO-ON Bot](https://github.com/Gunale0926/KO-ON-Bot)<br>音频部分来自[kook-voice-API](https://github.com/hank9999/kook-voice-API)<br>
#### 代码水平*极差*大部分使用ChatGPT和前人的作品实现功能 轻喷
***
项目名称是因为我的朋友Howard经常喜欢在打游戏的时候激情演唱他喜欢的歌曲 
<br>
而我实在无能为力欣赏他的美妙歌喉 不得已寻找更为方便的点歌机器人 方便我们更为愉快的打游戏
<br>
因为之前用的[*KO-ON Bot*](https://github.com/Gunale0926/KO-ON-Bot)经常出现一些问题 但由于本人*技术力过低*无法查出问题原因<br>
不如加上自己喜欢的功能再写一个点歌bot自用（Python真的很简单，现在已经成为了高中必学内容..）
<br>再加上ChatGPT和各种大佬做好的项目 不如自己学着做一个
<br>非常建议各位 **仔细阅读[khl.py](https://github.com/TWT233/khl.py)的文档内容** 这可以帮助你很多
***
## 机器人频道内指令前缀
代码内出现了部分用"/"为前缀的文字示例 仅为演示作用<br>代码最后已经修改了指令前缀为空 请自行修改满足需求
```python
bot.command.update_prefixes("")  # 修改引号内的内容为你的指令前缀 留空则无前缀 直接输入指令
```

### 使用方法

1.git本项目到本地

2.安装依赖
```shell
pip install -r requirements.txt
```

3.在项目文件夹内创建config文件夹 并于其中添加config.json文件 格式如下\
amap_api_key为高德地图API 需自行申请 即可使用/we 天气功能

```json
{
  "token": "KookdeveloperbotToken",
  "amap_api_key": "Gaode_WeatherAPI"
}
```

4.运行index.py
```shell
python index.py
```

## 小工具
### #机器人状态
***你也可以用更简单的办法 这样比较麻烦但很直观 所有操作都是GUI形式的***<br>

在脚本目录Tools文件夹内CreateGame.py内运行运行机器人状态生成器<br>
需要提前配置config文件保证token正确 机器人可以正常运行
之后在机器人所在任何文字频道内输入如下指令 机器人会在频道内返回你游戏ID 随后修改index.py使用
```shell
/game-c {游戏名称} {游戏LOGO URL}
```

注:项目暂未支持webhook模式 若需使用webhook模式请参照[khl.py](https://github.com/TWT233/khl.py)自行修改代码
