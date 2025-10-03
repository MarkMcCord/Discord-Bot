import os
import random
from time import sleep
from dotenv import load_dotenv
import discord
from discord import FFmpegPCMAudio
from discord.ext import commands
from gtts import gTTS

load_dotenv()
TOKEN = os.environ.get('TOKEN')
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents = intents)

voice_channel = os.environ.get('VOICE_CHANNEL')
text_channel = os.environ.get('TEXT_CHANNEL')

hello_goodbye = True

@bot.event
async def on_ready():
    try:
        global tchannel
        global vchannel
        tchannel = bot.get_channel(int(text_channel))
        vchannel = bot.get_channel(int(voice_channel))
        print('working probably')
        print(bot.user.name)
        #await tchannel.send('Hello World!')
        if len(vchannel.members) > 0:
            await vchannel.connect()
        await bot.change_presence(activity = discord.CustomActivity('✔️ !help'))
    except Exception as e:
        print(f"Something went wrong with on_ready: {e}")

@bot.command(name = 'disable', help = 'Disables welcome/goodbye messages in VC ❌')
async def disable(ctx):
    global hello_goodbye
    hello_goodbye = False
    print('Disabled welcome and goodbye.')
    await bot.change_presence(activity = discord.CustomActivity('❌ !help'))
    await ctx.message.delete()

@bot.command(name = 'enable', help = 'Enables welcome/goodbye messages in VC ✔️')
async def enable(ctx):
    global hello_goodbye
    hello_goodbye = True
    print('Enabled welcome and goodbye.')
    await bot.change_presence(activity = discord.CustomActivity('✔️ !help'))
    await ctx.message.delete()

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        global vchannel
        if hello_goodbye:
            #they joined voice
            if before.channel != after.channel and after.channel is not None:
                if after.channel.name == vchannel.name and member.id != bot.user.id:
                    #await member.guild.system_channel.send(member.name + ' just joined voice.')
                    nameToUse = str()
                    if member.nick == None:
                        nameToUse = member.name
                    else:
                        nameToUse = member.nick
                    clip = gTTS(text= "Welcome " + nameToUse, tld='com',lang='zh-CN')
                    clip.save("clip.mp3")
                    source = FFmpegPCMAudio('clip.mp3')
                    if bot.voice_clients:
                        while bot.voice_clients[0].is_playing():
                            sleep(1)
                        bot.voice_clients[0].play(source)
                    else:
                        vc = await vchannel.connect()
                        vc.play(source)
            #they left voice
            if before.channel is not None and after.channel != before.channel:
                if before.channel.name == vchannel.name and member.id != bot.user.id:
                    #await member.guild.system_channel.send(member.name + ' just left voice.')
                    nameToUse = str()
                    if member.nick == None:
                        nameToUse = member.name
                    else:
                        nameToUse = member.nick
                    clip = gTTS(text= "Goodbye " + nameToUse, tld='com',lang='zh-CN')
                    clip.save("clip.mp3")
                    source = FFmpegPCMAudio('clip.mp3')
                    if bot.voice_clients:
                        while bot.voice_clients[0].is_playing():
                            sleep(1)
                        bot.voice_clients[0].play(source)
                    else:
                        vc = await vchannel.connect()
                        vc.play(source)
                    #disconnect if no one else is in voice
                    while bot.voice_clients[0].is_playing():
                        sleep(1)
                    if len(before.channel.members) == 1:
                        await bot.voice_clients[0].disconnect()
        else:
            print('Hello and goodbye are currently disabled.')
            #disconnect if no one else is in voice
            if bot.voice_clients:
                while bot.voice_clients[0].is_playing():
                    sleep(1)
                if len(before.channel.members) == 1:
                    await bot.voice_clients[0].disconnect()
    except Exception as e:
        print(f"Something went wrong with on_voice_state_update: {e}")

@bot.event
async def on_voice_channel_effect(effect):
    try:
        global vchannel
        if (effect.emoji.name == '🦎'):
            source = FFmpegPCMAudio(os.path.join('gex', random.choice(os.listdir(os.path.join(os.getcwd(), 'gex')))))
            if bot.voice_clients:
                while bot.voice_clients[0].is_playing():
                    sleep(1)
                bot.voice_clients[0].play(source)
            else:
                vc = await vchannel.connect()
                vc.play(source)
            print('Gex Quote Here')
    except Exception as e:
        print(f"Something went wrong with on_voice_channel_effect: {e}")

bot.run(TOKEN)
