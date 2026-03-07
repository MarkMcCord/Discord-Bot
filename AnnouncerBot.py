import os
import random
from time import sleep
import discord
from discord import FFmpegPCMAudio
from discord.ext import commands
from gtts import gTTS
import asyncio
import mysql.connector

#region Database Setup

db_config = {
    'user': os.environ.get('DB_USER'),
    'password': open(os.environ.get('DB_PASSWORD_FILE'), 'r').read().strip(),
    'host': os.environ.get('DB_HOST'),
    'database': 'servers',
}

TABLES = {}
TABLES['servers'] = (
    "CREATE TABLE `servers` ("
    "  `id` int(11) NOT NULL AUTO_INCREMENT,"
    "  `guild_id` varchar(255) NOT NULL,"
    "  `voice_channel_id` varchar(255) NOT NULL,"
    "  `welcome_enabled` tinyint(1) NOT NULL DEFAULT '0',"
    "  PRIMARY KEY (`id`)"
    ") ENGINE=InnoDB"
)

#endregion

TOKEN = open(os.environ.get('TOKEN_FILE'), 'r').read().strip()
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents = intents)

keep_alive_task = None

@bot.event
async def on_ready():
    try:
        global vchannel
        global status
        global keep_alive_task

        vchannel = None
        starting_vc = None
        status = False

        cnx = mysql.connector.connect(**db_config)
        with cnx.cursor() as cursor:
            for table_name in TABLES: #Don't think I'll ever have more than one table, but just in case
                try:
                    cursor.execute(TABLES[table_name])
                    cnx.commit()
                    print(f"Table {table_name} created successfully.")
                except mysql.connector.Error as err:
                    if err.errno == mysql.connector.errorcode.ER_TABLE_EXISTS_ERROR:
                        print(f"Table {table_name} already exists.")
                    else:
                        print(err.msg)

            #To do: How to choose the right voice channel if there are multiple servers?
            #For testing, just get the first entry in the database if there is one
            cursor.execute("SELECT voice_channel_id FROM servers LIMIT 1")
            result = cursor.fetchone()
            if result:
                starting_vc = result[0]

        if starting_vc:
            vchannel = bot.get_channel(int(starting_vc))
        status = get_welcome_status()
        keep_alive_task = asyncio.create_task(keep_alive())
        await bot.change_presence(activity = discord.CustomActivity('!help'))
        await join_if_active()

        print(bot.user.name)
        if vchannel:
            print(f"Announcing in: {vchannel.name}")
        else:
            print("No voice channel set.")
        if status:
            print("Status: Enabled")
        else:
            print("Status: Disabled")

    except Exception as e:
        print(f"Something went wrong with on_ready: {e}")

async def keep_alive():
    try:
        global vchannel

        while True:
            if vchannel:
                vc = next((vc for vc in bot.voice_clients if vc.channel.id == vchannel.id), None)
                if vc and vc.is_playing() == False: #If we're already playing, we're don't need to keep alive
                    vc.send_audio_packet(b'\xF8\xFF\xFE', encode=False) #Should be silent but still count as saying something
                    print("Sending: Keep alive")
                await leave_if_empty() #May as well check, in case something weird happened
            await asyncio.sleep(60)

    except Exception as e:
        print(f"Something went wrong with keep_alive: {e}")

@bot.command(name = 'enable', help = 'Enables welcome/goodbye messages in VC. Use !setvc [channel name] to set the voice channel if you haven\'t already.')
async def enable(ctx):
    await set_welcome_status(ctx, 1)

@bot.command(name = 'disable', help = 'Disables welcome/goodbye messages in VC.')
async def disable(ctx):
    await set_welcome_status(ctx, 0)

@bot.command(name = 'setvc', help = 'Sets the voice channel for the bot to announce in. Usage: !setvc [channel name]')
async def setvc(ctx, *, channel_name):
    try:
        global vchannel

        new_vchannel = discord.utils.get(ctx.guild.voice_channels, name=channel_name)
        if new_vchannel:
            cnx = mysql.connector.connect(**db_config)
            with cnx.cursor() as cursor:
                cursor.execute("SELECT id FROM servers WHERE guild_id = %s", (str(ctx.guild.id),))
                result = cursor.fetchone()
                if result: #Entry for this server already exists, update it
                    cursor.execute("UPDATE servers "
                                "SET voice_channel_id = %s WHERE guild_id = %s", (str(new_vchannel.id), str(ctx.guild.id)))
                    cnx.commit()
                else: #No entry for this server, insert it with the chosen channel
                    cursor.execute("INSERT INTO servers "
                                "(guild_id, voice_channel_id) VALUES (%s, %s)", (str(ctx.guild.id), str(new_vchannel.id)))
                    cnx.commit()

            vchannel = new_vchannel
            await ctx.send(f"Voice channel set to: {vchannel.name}")
        else:
            await ctx.send("Voice channel not found.")

    except Exception as e:
        print(f"Something went wrong with setvc: {e}")
    

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        global vchannel
        global status

        if vchannel:
            if status:
                #Case where they joined voice
                if before.channel != after.channel and after.channel is not None:
                    if after.channel.name == vchannel.name and member.bot == False:
                        #await member.guild.system_channel.send(member.name + ' just joined voice.')
                        clip = gTTS(text= "Welcome " + member.display_name, tld='com',lang='zh-CN')
                        clip.save("clip.mp3")
                        source = FFmpegPCMAudio('clip.mp3')
                        await play_queued(source)
                        print("Sending: Welcome " + member.display_name)
                #Case where they left voice
                if before.channel is not None and after.channel != before.channel:
                    if before.channel.name == vchannel.name and member.bot == False:
                        #await member.guild.system_channel.send(member.name + ' just left voice.')
                        clip = gTTS(text= "Goodbye " + member.display_name, tld='com',lang='zh-CN')
                        clip.save("clip.mp3")
                        source = FFmpegPCMAudio('clip.mp3')
                        await play_queued(source)
                        print("Sending: Goodbye " + member.display_name)
                        #Disconnect if no one else is in voice
                        await leave_if_empty()
            else:
                print('Hello and goodbye are currently disabled.')

    except Exception as e:
        print(f"Something went wrong with on_voice_state_update: {e}")

@bot.event
async def on_voice_channel_effect(effect):
    try:
        global vchannel
        global status

        if vchannel and status and effect.emoji.name == '🦎':
            source = FFmpegPCMAudio(os.path.join('gex', random.choice(os.listdir(os.path.join(os.getcwd(), 'gex')))))
            await play_queued(source)
            print('Sending: Gex Quote')

    except Exception as e:
        print(f"Something went wrong with on_voice_channel_effect: {e}")

#region Helper methods

def get_welcome_status():
    try:
        global vchannel

        if vchannel:
            cnx = mysql.connector.connect(**db_config)
            with cnx.cursor() as cursor:
                cursor.execute("SELECT welcome_enabled FROM servers WHERE guild_id = %s", (str(vchannel.guild.id),))
                result = cursor.fetchone()
                if result:
                    return bool(result[0])
                
        return False #Status is irrelevant if we don't have a voice channel set, return false to be safe

    except Exception as e:
        print(f"Something went wrong with get_welcome_status: {e}")

async def set_welcome_status(ctx, new_status):
    try:
        global vchannel
        global status

        if vchannel: #Status is irrelevant if we don't have a voice channel set
            cnx = mysql.connector.connect(**db_config)
            with cnx.cursor() as cursor:
                cursor.execute("UPDATE servers "
                            "SET welcome_enabled = %s WHERE guild_id = %s", (new_status, str(ctx.guild.id)))
                cnx.commit()
            status = bool(new_status)

            if status:
                await ctx.send('Enabled welcome and goodbye.')
                #Need to join if enabled
                await join_if_active()
            else:
                await ctx.send('Disabled welcome and goodbye.')
                #Need to leave if disabled
                voice_client = next((vc for vc in bot.voice_clients if vc.channel.id == vchannel.id), None)
                if voice_client:
                    while voice_client.is_playing():
                        sleep(1)
                    await voice_client.disconnect()
        else:
            await ctx.send('Please set a voice channel first using !setvc [channel name]')

    except Exception as e:
        print(f"Something went wrong with set_welcome_status: {e}")

async def play_queued(source):
    try:
        global vchannel

        if vchannel: #We should always have a voice channel assigned at this point, but just to be safe
            vc = next((vc for vc in bot.voice_clients if vc.channel.id == vchannel.id), None)
            if vc: #If we're already connected, wait for the current audio to finish and then play the new one
                while vc.is_playing():
                    sleep(1)
                vc.play(source)
            else: #If we're not connected, connect and play the audio
                vc = await vchannel.connect()
                vc.play(source)
            return vc
        return None

    except Exception as e:
        print(f"Something went wrong with play_queued: {e}")

async def join_if_active():
    try:
        global vchannel
        global status

        if vchannel and status and len(vchannel.members) > 0:
            voice_client = next((vc for vc in bot.voice_clients if vc.channel.id == vchannel.id), None)
            if not voice_client: #Don't try to join if we're already connected for some reason
                await vchannel.connect()

    except Exception as e:
        print(f"Something went wrong with join_if_active: {e}")

async def leave_if_empty():
    try:
        global vchannel

        if vchannel: #Hopefully impossible to be in VC without vchannel being set
            voice_client = next((vc for vc in bot.voice_clients if vc.channel.id == vchannel.id), None)
            if voice_client:
                while voice_client.is_playing():
                    sleep(1)
                if len(vchannel.members) == 1: #If there's only one member left in the channel, it's the bot
                    await voice_client.disconnect()

    except Exception as e:
        print(f"Something went wrong with leave_if_empty: {e}")
    
#endregion

bot.run(TOKEN)
#To do: How to leave vc before stopping the bot?