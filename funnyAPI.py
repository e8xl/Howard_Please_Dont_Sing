import csv
import json
import os
import random
import traceback
from datetime import datetime, timedelta

import aiofiles
import aiohttp
from khl import Bot, Message
from khl.card import Card, CardMessage, Element, Module, Types

with open('./config/config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

bot = Bot(token=config['token'])


# 获取城市的adcode
async def get_adcode(api_key, address):
    api_url = f"https://restapi.amap.com/v3/geocode/geo?key={api_key}&address={address}"

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            if response.status == 200:
                geocode_data = await response.json()
                if geocode_data["status"] == "1" and geocode_data["count"] == "1":
                    return geocode_data["geocodes"][0]["adcode"]
                else:
                    print("获取adcode失败")
                    return None
            else:
                print("API请求失败")
                return None


# 获取天气信息
async def fetch_weather_data(api_key, city_code):
    api_url = f"https://restapi.amap.com/v3/weather/weatherInfo?key={api_key}&extensions=all&city={city_code}"

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            if response.status == 200:
                weather_data = await response.json()
                return weather_data
            else:
                print("API请求失败")
                return None


# 发送天气信息
async def send_weather_message(msg: Message, city: str, weather_data):
    current_time = datetime.now()
    cm = CardMessage()
    c1 = Card(Module.Header(
        f"已为您查询 {city} 的天气\n"
        f"更新于 {weather_data['forecasts'][0]['reporttime']}"),  # 可将{city}更换为 {weather_data['forecasts'][0]['city']}
        Module.Context(f'实际查询地区为：{weather_data["forecasts"][0]["city"]}\n'
                       f'天高云淡，望断南飞雁...\n'
                       f"当前UTC+8时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"))  # 时间为本地服务器时间 可按需调整

    # 使用datetime计算"今天"、"明天"和"后天"的日期
    today = datetime.now()
    days = ["今天", "明天", "后天"]

    c1.append(Module.Divider())

    for i, forecast in enumerate(weather_data['forecasts'][0]['casts'][:3]):
        date_str = (today + timedelta(days=i)).strftime('%Y-%m-%d')
        dayweather = forecast['dayweather']
        daytemp = forecast['daytemp']
        nighttemp = forecast['nighttemp']
        c1.append(
            Module.Section(
                f"日期: {date_str}（{days[i]}） 天气: {dayweather} 温度: {daytemp}℃~{nighttemp}℃"
            )
        )
        c1.append(Module.Divider())

    c1.append(Module.Context(
        Element.Text(f'天气部分来自高德天气，部分结果可能有出入，数据更新不及时敬请谅解\n'
                     '暂不支持除 **中国大陆** 省市区(县)以外的地区', Types.Text.KMD)))
    cm.append(c1)
    await msg.reply(cm)


def we_function(city):
    async def we(msg: Message, city: str = city):
        if city == "err":
            await msg.reply(f"函数参数错误，城市: `{city}`\n")
            return

        try:
            # 获取城市的adcode，不需要传递msg参数
            city_code = await get_adcode(config['amap_api_key'], city)

            if city_code:
                # 获取天气信息
                weather_list = await fetch_weather_data(config['amap_api_key'], city_code)

                if weather_list:
                    await send_weather_message(msg, city, weather_list)
                else:
                    await msg.reply("获取天气信息失败。")
            else:
                await msg.reply("请检查城市名称是否正确，是否为中国大陆的省市区(县)。")
        except Exception as result:
            await msg.reply(f"发生错误: {str(result)}")
            print(traceback.format_exc())  # 返回错误原因

    return we


# 使用函数工厂创建we函数
we = we_function("err")

'''
不稳定暂时停用

# 一言API
async def get_hitokoto():
    api_url = "https://v1.hitokoto.cn/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.0.0 Safari/537.36"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url, headers=headers) as response:
            if response.status == 200:
                hitokoto = await response.json()
                hitokoto_text = hitokoto.get("hitokoto")
                return hitokoto_text  # 返回一言文本
            else:
                print("API请求失败")
                return None
'''


# LocalHitokoto
async def local_hitokoto():
    # 获取当前脚本的目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, 'Tools', 'hitokoto.csv')

    # 读取CSV文件内容
    async with aiofiles.open(csv_path, mode='r', encoding='utf-8') as f:
        content = await f.read()

    # 按行分割内容
    lines = content.splitlines()

    # 使用csv.DictReader解析CSV内容
    reader = csv.DictReader(lines)

    # 收集所有的hitokoto
    hitokotos = []
    for row in reader:
        if isinstance(row, dict) and 'hitokoto' in row:
            hitokotos.append(row['hitokoto'])

    # 随机选择一个hitokoto并返回
    if hitokotos:
        return random.choice(hitokotos)
    else:
        return "没有找到任何hitokoto。"
