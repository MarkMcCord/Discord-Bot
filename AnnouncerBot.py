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

@bot.event
async def on_ready():
    try:
        global voice_channels #Key is voice channel ID, value is enable/disable status for that channel
        global keep_alive_tasks

        voice_channels = {}
        keep_alive_tasks = []

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

            #Load all of the voice channels and their enabled/disabled status into memory
            #To do: I doubt this approach is scalable, but I'm only testing with 2 servers currently
            cursor.execute("SELECT voice_channel_id, welcome_enabled FROM servers")
            result = cursor.fetchall()
            for row in result:
                voice_channels[int(row[0])] = bool(row[1])

        await bot.change_presence(activity = discord.CustomActivity('!help'))

        print(bot.user.name)
        for channel_id in voice_channels:
            voice_channel = bot.get_channel(channel_id)
            await join_if_active(voice_channel, voice_channels[channel_id])
            keep_alive_tasks.append(asyncio.create_task(keep_alive(voice_channel)))
            print(f"Announcing in: {voice_channel.name}")
            if voice_channels[channel_id]:
                print("Status: Enabled")
            else:
                print("Status: Disabled")

    except Exception as e:
        print(f"Something went wrong with on_ready: {e}")

async def keep_alive(voice_channel):
    #To do: some way to skip the loop if we sent a message recently (may require a mutex or something)
    try:
        while True:
            if voice_channel:
                voice_client = get_voice_client(voice_channel)
                if voice_client and voice_client.is_playing() == False: #If we're already playing, we're don't need to keep alive
                    voice_client.send_audio_packet(b'\xF8\xFF\xFE', encode=False) #Should be silent but still count as saying something
                    print("Sending: Keep alive")
                await leave_if_empty(voice_channel) #May as well check, in case something weird happened
            await asyncio.sleep(60)

    except Exception as e:
        print(f"Something went wrong with keep_alive: {e}")

@bot.command(name = 'enable', help = 'Enables welcome/goodbye messages in VC. Use !setvc [channel name] to set the voice channel if you haven\'t already.')
async def enable(ctx):
    await set_welcome_status(ctx, 1) #Sending 1 rather than True, since that's how the db is set up.

@bot.command(name = 'disable', help = 'Disables welcome/goodbye messages in VC.')
async def disable(ctx):
    await set_welcome_status(ctx, 0)

@bot.command(name = 'setvc', help = 'Sets the voice channel for the bot to announce in. Usage: !setvc [channel name]')
async def setvc(ctx, *, channel_name):
    try:
        global voice_channels
        
        new_voice_channel = discord.utils.get(ctx.guild.voice_channels, name=channel_name)
        if new_voice_channel:
            cnx = mysql.connector.connect(**db_config)
            with cnx.cursor() as cursor:
                cursor.execute("SELECT id FROM servers WHERE guild_id = %s", (str(ctx.guild.id),))
                result = cursor.fetchone()
                if result: #Entry for this server already exists, update it in db and in memory
                    cursor.execute("UPDATE servers "
                                "SET voice_channel_id = %s WHERE guild_id = %s", (str(new_voice_channel.id), str(ctx.guild.id)))
                    cnx.commit()
                    #Move the welcome status to the new channel's entry and remove the old entry from the dictionary
                    old_voice_channel = get_voice_channel(ctx.guild.id)
                    if old_voice_channel:
                        voice_channels[new_voice_channel.id] = voice_channels.pop(old_voice_channel.id)
                else: #No entry for this server, insert it with the chosen channel
                    cursor.execute("INSERT INTO servers "
                                "(guild_id, voice_channel_id, welcome_enabled) VALUES (%s, %s, %s)", (str(ctx.guild.id), str(new_voice_channel.id), 1))
                    cnx.commit()
                    #Add a new entry to our dictionary
                    voice_channels[new_voice_channel.id] = True #Default to enabled, I'll see how people feel about it

            await ctx.send(f"Voice channel set to: {new_voice_channel.name}")
        else:
            await ctx.send("Voice channel not found.")

    except Exception as e:
        print(f"Something went wrong with setvc: {e}")
    

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        global voice_channels

        voice_channel = get_voice_channel(member.guild.id)
        if voice_channel:
            if voice_channels[voice_channel.id]: #This is that status for that channel
                #Case where they joined voice
                if before.channel != after.channel and after.channel is not None:
                    if after.channel.name == voice_channel.name and member.bot == False:
                        #await member.guild.system_channel.send(member.name + ' just joined voice.')
                        clip = gTTS(text= "Welcome " + member.display_name, tld='com',lang='zh-CN')
                        clip.save("clip.mp3")
                        source = FFmpegPCMAudio('clip.mp3')
                        await play_queued(voice_channel, source)
                        print("Sending: Welcome " + member.display_name)
                #Case where they left voice
                if before.channel is not None and after.channel != before.channel:
                    if before.channel.name == voice_channel.name and member.bot == False:
                        #await member.guild.system_channel.send(member.name + ' just left voice.')
                        clip = gTTS(text= "Goodbye " + member.display_name, tld='com',lang='zh-CN')
                        clip.save("clip.mp3")
                        source = FFmpegPCMAudio('clip.mp3')
                        await play_queued(voice_channel, source)
                        print("Sending: Goodbye " + member.display_name)
                        #Disconnect if no one else is in voice
                        await leave_if_empty(voice_channel)
            else:
                print('Hello and goodbye are currently disabled.')

    except Exception as e:
        print(f"Something went wrong with on_voice_state_update: {e}")

@bot.event
async def on_voice_channel_effect(effect):
    try:
        global voice_channels

        voice_channel = get_voice_channel(effect.channel.guild.id)
        if voice_channel and voice_channels[voice_channel.id] and effect.emoji.name == '🦎':
            source = FFmpegPCMAudio(os.path.join('gex', random.choice(os.listdir(os.path.join(os.getcwd(), 'gex')))))
            await play_queued(voice_channel, source)
            print('Sending: Gex Quote')

    except Exception as e:
        print(f"Something went wrong with on_voice_channel_effect: {e}")

#region Helper methods

def get_voice_channel(guild_id):
    #Get the voice channel that's been set for the given guild
    #To do: might be more efficient to search the db for this
    return next((bot.get_channel(vc) for vc in voice_channels if bot.get_channel(vc).guild.id == guild_id), None)

def get_voice_client(voice_channel):
    #Get the voice client that's connected to the given voice channel
    return next((vc for vc in bot.voice_clients if vc.channel.id == voice_channel.id), None)

async def set_welcome_status(ctx, new_status):
    try:
        global voice_channels

        voice_channel = get_voice_channel(ctx.guild.id)
        if voice_channel: #Status is irrelevant if we don't have a voice channel set
            cnx = mysql.connector.connect(**db_config)
            with cnx.cursor() as cursor:
                cursor.execute("UPDATE servers "
                            "SET welcome_enabled = %s WHERE guild_id = %s", (new_status, str(ctx.guild.id)))
                cnx.commit()
            voice_channels[voice_channel.id] = bool(new_status)

            if voice_channels[voice_channel.id]:
                await ctx.send('Enabled welcome and goodbye.')
                #Need to join if enabled
                await join_if_active(voice_channel, voice_channels[voice_channel.id])
            else:
                await ctx.send('Disabled welcome and goodbye.')
                #Need to leave if disabled
                voice_client = get_voice_client(voice_channel)
                if voice_client:
                    while voice_client.is_playing():
                        sleep(1)
                    await voice_client.disconnect()
        else:
            await ctx.send('Please set a voice channel first using !setvc [channel name]')

    except Exception as e:
        print(f"Something went wrong with set_welcome_status: {e}")

async def play_queued(voice_channel, source):
    try:
        global alive
        
        if voice_channel: #We should always have a voice channel assigned at this point, but just to be safe
            voice_client = get_voice_client(voice_channel)
            if voice_client: #If we're already connected, wait for the current audio to finish and then play the new one
                while voice_client.is_playing():
                    sleep(1)
                voice_client.play(source)
            else: #If we're not connected, connect and play the audio
                voice_client = await voice_channel.connect()
                voice_client.play(source)

    except Exception as e:
        print(f"Something went wrong with play_queued: {e}")

async def join_if_active(voice_channel, status):
    try:
        if voice_channel and status and len(voice_channel.members) > 0:
            voice_client = get_voice_client(voice_channel)
            if not voice_client: #Don't try to join if we're already connected for some reason
                await voice_channel.connect()

    except Exception as e:
        print(f"Something went wrong with join_if_active: {e}")

async def leave_if_empty(voice_channel):
    try:
        if voice_channel: #Hopefully impossible to be in VC without voice_channel being set
            voice_client = get_voice_client(voice_channel)
            if voice_client:
                while voice_client.is_playing():
                    sleep(1)
                if len(voice_channel.members) == 1: #If there's only one member left in the channel, it's the bot
                    await voice_client.disconnect()

    except Exception as e:
        print(f"Something went wrong with leave_if_empty: {e}")
    
#endregion

bot.run(TOKEN)
#To do: How to leave any VCs before stopping the bot?