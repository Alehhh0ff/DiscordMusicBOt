import discord
import wavelink
from discord.ext import commands
from typing import cast
from config import BOT

# --- 1. КЛАСС ПЛЕЕРА ---
class CustomPlayer(wavelink.Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Сохраняем канал, куда бот будет писать о следующем треке
        self.bound_channel: discord.TextChannel | None = None

# --- 2. КНОПКИ УПРАВЛЕНИЯ (UI) ---
class PlayerControls(discord.ui.View):
    def __init__(self, player: CustomPlayer):
        super().__init__(timeout=None)
        self.player = player

    @discord.ui.button(label="⏸️ Пауза / ▶️ Плей", style=discord.ButtonStyle.blurple)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.player.connected:
            return await interaction.response.send_message("Бот не в голосовом канале.", ephemeral=True)
        
        await self.player.pause(not self.player.paused)
        status = "на паузе ⏸️" if self.player.paused else "продолжает играть ▶️"
        await interaction.response.send_message(f"Музыка {status}.", ephemeral=True)

    @discord.ui.button(label="⏭️ Скип", style=discord.ButtonStyle.success)
    async def skip_track(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.player.connected or not self.player.playing:
            return await interaction.response.send_message("Очередь пуста или ничего не играет.", ephemeral=True)
        
        # Останавливаем текущий трек (это автоматически запустит следующий из очереди)
        await self.player.stop()
        await interaction.response.send_message("⏭️ Трек пропущен!", ephemeral=True)

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.danger)
    async def stop_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.player.connected:
            self.player.queue.clear() # Полностью чистим очередь
            await self.player.disconnect()
            await interaction.response.send_message("⏹️ Очередь очищена, бот отключен.", ephemeral=True)

# --- 3. НАСТРОЙКА БОТА ---
class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=BOT['PREFIX'], intents=intents)

    async def setup_hook(self):
        node = wavelink.Node(
            uri=f"http://{BOT['LAVALINK_HOST']}:{BOT['LAVALINK_PORT']}",
            password=BOT['LAVALINK_PASSWORD']
        )
        await wavelink.Pool.connect(nodes=[node], client=self)
        print(f"✅ Бот подключен к локальному Lavalink: {BOT['LAVALINK_HOST']}")
        await self.tree.sync()

bot = MusicBot()

# --- 4. СОБЫТИЕ: АВТОМАТИЧЕСКАЯ ОЧЕРЕДЬ ---
@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
    player: CustomPlayer = payload.player
    
    # Если бот отключился или очередь пуста — ничего не делаем
    if not player or not player.connected or player.queue.is_empty:
        return

    # Берем следующий трек из очереди и запускаем
    next_track = player.queue.get()
    await player.play(next_track)

    # Отправляем сообщение с кнопками в тот же канал
    if player.bound_channel:
        embed = discord.Embed(
            title="▶️ Сейчас играет (из очереди)",
            description=f"**[{next_track.title}]({next_track.uri})**",
            color=discord.Color.brand_green()
        )
        embed.set_footer(text=f"Треков осталось в очереди: {player.queue.count}")
        await player.bound_channel.send(embed=embed, view=PlayerControls(player))

# --- 5. КОМАНДЫ ---
@bot.hybrid_command(name="play", description="Включить трек или добавить его в очередь")
async def play(ctx: commands.Context, *, query: str):
    await ctx.defer()

    if not ctx.author.voice:
        return await ctx.send("Сначала зайди в голосовой канал!")

    # Подключаем кастомного плеера
    player = cast(CustomPlayer, ctx.voice_client)
    if not player:
        player = await ctx.author.voice.channel.connect(cls=CustomPlayer)
    
    player.bound_channel = ctx.channel

    tracks = await wavelink.Playable.search(query, source="ytsearch")
    if not tracks:
        return await ctx.send("❌ По запросу ничего не найдено.")

    track = tracks[0]

    # Если музыка УЖЕ играет — просто кидаем в очередь
    if player.playing:
        await player.queue.put_wait(track)
        embed = discord.Embed(
            title="📜 Добавлено в очередь",
            description=f"**{track.title}**",
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Позиция в очереди: {player.queue.count}")
        return await ctx.send(embed=embed)

    # Если ничего не играет — запускаем сразу
    await player.queue.put_wait(track)
    await player.play(player.queue.get())

    embed = discord.Embed(
        title="▶️ Сейчас играет",
        description=f"**[{track.title}]({track.uri})**",
        color=discord.Color.brand_green()
    )
    await ctx.send(embed=embed, view=PlayerControls(player))

# Запуск
bot.run(BOT['TOKEN'])

