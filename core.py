import json
from khl import Bot, Message, ChannelPrivacyTypes
from khl.card import Card, CardMessage, Element, Module, Types
import aiohttp
import traceback

from voiceAPI import Voice

with open('./config/config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

bot = Bot(token=config['token'])
voice = Voice(token=config['token'])

