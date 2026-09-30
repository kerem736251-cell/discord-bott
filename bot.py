import os
import random
import secrets
import sqlite3
import asyncio
from datetime import timedelta
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "")
DEFAULT_GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
LICENSE_API_URL = os.getenv("LICENSE_API_URL", "").strip()
LICENSE_API_SECRET = os.getenv("LICENSE_API_SECRET", "").strip()

# Quantix defaults (can still be changed later with /setup)
DEFAULT_WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0") or 0)
DEFAULT_LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0") or 0)
DEFAULT_AUX_LOG_CHANNEL_ID_1 = int(os.getenv("AUX_LOG_CHANNEL_ID_1", "0") or 0)
DEFAULT_AUX_LOG_CHANNEL_ID_2 = int(os.getenv("AUX_LOG_CHANNEL_ID_2", "0") or 0)
DEFAULT_PRO_ROLE_ID = int(os.getenv("PRO_ROLE_ID", "0") or 0)
DEFAULT_ELITE_ROLE_ID = int(os.getenv("ELITE_ROLE_ID", "0") or 0)
DEFAULT_SUPPORT_ROLE_ID = int(os.getenv("SUPPORT_ROLE_ID", "0") or 0)
DEFAULT_TICKET_PANEL_CHANNEL_ID = int(os.getenv("TICKET_PANEL_CHANNEL_ID", "0") or 0)
DEFAULT_TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0") or 0)

DB_PATH = "quantix.db"


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            welcome_channel_id INTEGER DEFAULT 0,
            log_channel_id INTEGER DEFAULT 0,
            customer_role_id INTEGER DEFAULT 0,
            pro_role_id INTEGER DEFAULT 0,
            elite_role_id INTEGER DEFAULT 0,
            ticket_category_id INTEGER DEFAULT 0,
            support_role_id INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS verify_codes (
            code TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            used_by INTEGER DEFAULT 0,
            created_by INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tickets (
            channel_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS giveaways (
            message_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            ended INTEGER DEFAULT 0
        );
        """
    )
    con.commit()
    con.close()


def settings_for(guild_id: int):
    con = db()
    row = con.execute("SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,)).fetchone()
    if not row:
        con.execute(
            """INSERT INTO guild_settings(
                guild_id, welcome_channel_id, log_channel_id, pro_role_id, elite_role_id,
                ticket_category_id, support_role_id
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                guild_id, DEFAULT_WELCOME_CHANNEL_ID, DEFAULT_LOG_CHANNEL_ID,
                DEFAULT_PRO_ROLE_ID, DEFAULT_ELITE_ROLE_ID, DEFAULT_TICKET_CATEGORY_ID,
                DEFAULT_SUPPORT_ROLE_ID,
            ),
        )
        con.commit()
        row = con.execute("SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,)).fetchone()
    con.close()
    return row


intents = discord.Intents.default()
intents.members = True
intents.message_content = False

bot = commands.Bot(command_prefix="!", intents=intents)


def quantix_embed(title: str, description: str = "", *, success: Optional[bool] = None):
    if success is True:
        color = discord.Color.green()
    elif success is False:
        color = discord.Color.red()
    else:
        color = discord.Color.from_rgb(139, 92, 246)
    em = discord.Embed(title=title, description=description, color=color)
    em.set_footer(text="Quantix • Performance. Refined.")
    return em


async def log_event(guild: discord.Guild, text: str):
    s = settings_for(guild.id)
    cid = int(s["log_channel_id"] or 0)
    if cid:
        ch = guild.get_channel(cid)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.send(embed=quantix_embed("Quantix Log", text))
            except discord.HTTPException:
                pass


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="quantix:open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("This only works in a server.", ephemeral=True)

        con = db()
        existing = con.execute(
            "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'",
            (guild.id, interaction.user.id),
        ).fetchone()
        con.close()
        if existing and guild.get_channel(existing["channel_id"]):
            return await interaction.response.send_message(
                f"You already have an open ticket: <#{existing['channel_id']}>", ephemeral=True
            )

        s = settings_for(guild.id)
        category = guild.get_channel(int(s["ticket_category_id"] or 0))
        support_role = guild.get_role(int(s["support_role_id"] or 0))
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        name = f"ticket-{interaction.user.name}"[:90].lower().replace(" ", "-")
        channel = await guild.create_text_channel(name, category=category if isinstance(category, discord.CategoryChannel) else None, overwrites=overwrites)
        con = db()
        con.execute("INSERT OR REPLACE INTO tickets(channel_id,guild_id,user_id,status) VALUES(?,?,?,'open')",
                    (channel.id, guild.id, interaction.user.id))
        con.commit(); con.close()

        await channel.send(interaction.user.mention, embed=quantix_embed(
            "Quantix Support",
            "Tell us what you need help with. A staff member will be with you as soon as possible.\n\nUse **/closeticket** when the issue is solved."
        ))
        await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
        await log_event(guild, f"🎫 Ticket opened by {interaction.user.mention}: {channel.mention}")


class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.users = set()

    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.success, emoji="🎉", custom_id="quantix:giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.users.add(interaction.user.id)
        await interaction.response.send_message("You're entered! 🎉", ephemeral=True)


@bot.event
async def on_ready():
    bot.add_view(TicketView())
    try:
        if DEFAULT_GUILD_ID:
            guild_obj = discord.Object(id=DEFAULT_GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
        else:
            synced = await bot.tree.sync()
        print(f"Logged in as {bot.user} | synced {len(synced)} commands")
    except Exception as e:
        print(f"Command sync failed: {e}")


@bot.event
async def on_member_join(member: discord.Member):
    s = settings_for(member.guild.id)
    cid = int(s["welcome_channel_id"] or 0)
    if not cid:
        return
    channel = member.guild.get_channel(cid)
    if isinstance(channel, discord.TextChannel):
        em = quantix_embed(
            "Welcome to Quantix 💜",
            f"Hey {member.mention}, welcome to **{member.guild.name}**!\n\nCheck the rules, grab your roles and open a ticket if you need help."
        )
        em.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=em)


@bot.tree.command(name="ping", description="Check the Quantix bot latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 **{round(bot.latency * 1000)}ms**", ephemeral=True)


@bot.tree.command(name="setup", description="Configure Quantix bot channels and roles")
@app_commands.checks.has_permissions(administrator=True)
async def setup(
    interaction: discord.Interaction,
    welcome_channel: Optional[discord.TextChannel] = None,
    log_channel: Optional[discord.TextChannel] = None,
    customer_role: Optional[discord.Role] = None,
    pro_role: Optional[discord.Role] = None,
    elite_role: Optional[discord.Role] = None,
    ticket_category: Optional[discord.CategoryChannel] = None,
    support_role: Optional[discord.Role] = None,
):
    guild = interaction.guild
    if not guild:
        return await interaction.response.send_message("Server only.", ephemeral=True)
    current = settings_for(guild.id)
    vals = {
        "welcome_channel_id": welcome_channel.id if welcome_channel else current["welcome_channel_id"],
        "log_channel_id": log_channel.id if log_channel else current["log_channel_id"],
        "customer_role_id": customer_role.id if customer_role else current["customer_role_id"],
        "pro_role_id": pro_role.id if pro_role else current["pro_role_id"],
        "elite_role_id": elite_role.id if elite_role else current["elite_role_id"],
        "ticket_category_id": ticket_category.id if ticket_category else current["ticket_category_id"],
        "support_role_id": support_role.id if support_role else current["support_role_id"],
    }
    con = db()
    con.execute(
        """UPDATE guild_settings SET welcome_channel_id=?,log_channel_id=?,customer_role_id=?,pro_role_id=?,elite_role_id=?,ticket_category_id=?,support_role_id=? WHERE guild_id=?""",
        (*vals.values(), guild.id),
    )
    con.commit(); con.close()
    await interaction.response.send_message(embed=quantix_embed("Setup saved ✅", "Quantix bot configuration has been updated.", success=True), ephemeral=True)


@bot.tree.command(name="ticketpanel", description="Post the Quantix support ticket panel")
@app_commands.checks.has_permissions(administrator=True)
async def ticketpanel(interaction: discord.Interaction):
    em = quantix_embed("Quantix Support", "Need help with your purchase, utility, license or setup?\n\nClick the button below to open a private support ticket.")
    guild = interaction.guild
    target = guild.get_channel(DEFAULT_TICKET_PANEL_CHANNEL_ID) if guild and DEFAULT_TICKET_PANEL_CHANNEL_ID else None
    if isinstance(target, discord.TextChannel) and interaction.channel_id != target.id:
        await target.send(embed=em, view=TicketView())
        await interaction.response.send_message(f"Ticket panel posted in {target.mention} ✅", ephemeral=True)
    else:
        await interaction.response.send_message(embed=em, view=TicketView())


@bot.tree.command(name="closeticket", description="Close the current support ticket")
async def closeticket(interaction: discord.Interaction):
    guild = interaction.guild
    channel = interaction.channel
    if not guild or not isinstance(channel, discord.TextChannel):
        return await interaction.response.send_message("Server text channels only.", ephemeral=True)
    con = db()
    row = con.execute("SELECT * FROM tickets WHERE channel_id=? AND status='open'", (channel.id,)).fetchone()
    if not row:
        con.close()
        return await interaction.response.send_message("This is not an open Quantix ticket.", ephemeral=True)
    s = settings_for(guild.id)
    support_role = guild.get_role(int(s["support_role_id"] or 0))
    can_close = interaction.user.id == row["user_id"] or interaction.user.guild_permissions.manage_channels or (support_role and support_role in interaction.user.roles)
    if not can_close:
        con.close()
        return await interaction.response.send_message("You can't close this ticket.", ephemeral=True)
    con.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (channel.id,))
    con.commit(); con.close()
    await interaction.response.send_message("Closing ticket in 3 seconds…")
    await log_event(guild, f"🔒 Ticket closed by {interaction.user.mention}: #{channel.name}")
    await asyncio.sleep(3)
    await channel.delete(reason=f"Ticket closed by {interaction.user}")


@bot.tree.command(name="announce", description="Post a professional Quantix announcement")
@app_commands.checks.has_permissions(manage_guild=True)
async def announce(interaction: discord.Interaction, title: str, message: str, channel: Optional[discord.TextChannel] = None):
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        return await interaction.response.send_message("Choose a text channel.", ephemeral=True)
    await target.send(embed=quantix_embed(title, message))
    await interaction.response.send_message("Announcement posted ✅", ephemeral=True)


@bot.tree.command(name="createcode", description="Create a one-use customer verification code")
@app_commands.choices(tier=[
    app_commands.Choice(name="Customer", value="customer"),
    app_commands.Choice(name="Pro", value="pro"),
    app_commands.Choice(name="Elite", value="elite"),
])
@app_commands.checks.has_permissions(administrator=True)
async def createcode(interaction: discord.Interaction, tier: app_commands.Choice[str]):
    code = f"QX-{secrets.token_hex(4).upper()}"
    con = db()
    con.execute("INSERT INTO verify_codes(code,tier,created_by) VALUES(?,?,?)", (code, tier.value, interaction.user.id))
    con.commit(); con.close()
    await interaction.response.send_message(f"🔑 **{tier.name} code:** `{code}`\nOne-time use.", ephemeral=True)


async def verify_with_api(code: str, discord_id: int):
    if not LICENSE_API_URL:
        return None
    headers = {"Authorization": f"Bearer {LICENSE_API_SECRET}"} if LICENSE_API_SECRET else {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(LICENSE_API_URL, json={"key": code, "discord_id": str(discord_id)}, headers=headers, timeout=10) as r:
                if r.status != 200:
                    return {"ok": False}
                return await r.json()
    except Exception:
        return {"ok": False}


@bot.tree.command(name="verify", description="Verify your Quantix purchase/license")
async def verify(interaction: discord.Interaction, code: str):
    guild = interaction.guild
    if not guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("Server only.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    api_result = await verify_with_api(code.strip(), interaction.user.id)
    tier = None
    if api_result is not None:
        if api_result.get("ok"):
            tier = str(api_result.get("tier", "customer")).lower()
        else:
            return await interaction.followup.send("❌ That license could not be verified.")
    else:
        con = db()
        row = con.execute("SELECT * FROM verify_codes WHERE code=?", (code.strip().upper(),)).fetchone()
        if not row or row["used"]:
            con.close()
            return await interaction.followup.send("❌ Invalid or already-used verification code.")
        tier = row["tier"]
        con.execute("UPDATE verify_codes SET used=1, used_by=? WHERE code=?", (interaction.user.id, row["code"]))
        con.commit(); con.close()

    s = settings_for(guild.id)
    role_id = {
        "elite": int(s["elite_role_id"] or 0),
        "pro": int(s["pro_role_id"] or 0),
        "customer": int(s["customer_role_id"] or 0),
    }.get(tier, int(s["customer_role_id"] or 0))
    role = guild.get_role(role_id)
    if not role:
        return await interaction.followup.send("⚠️ License verified, but the matching role is not configured. Ask staff to run `/setup`.")
    try:
        await interaction.user.add_roles(role, reason="Quantix purchase verification")
    except discord.Forbidden:
        return await interaction.followup.send("⚠️ Verified, but I cannot assign the role. Move the bot role above the customer roles.")
    await interaction.followup.send(f"✅ Verified as **{tier.title()}**. You now have {role.mention}.")
    await log_event(guild, f"✅ {interaction.user.mention} verified as **{tier.title()}**")


@bot.tree.command(name="clear", description="Delete recent messages")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    if not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("Text channel only.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Deleted **{len(deleted)}** messages.")


@bot.tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    await member.kick(reason=f"{reason} | By {interaction.user}")
    await interaction.response.send_message(f"👢 Kicked **{member}** — {reason}")
    if interaction.guild: await log_event(interaction.guild, f"👢 {member} kicked by {interaction.user.mention}: {reason}")


@bot.tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    await member.ban(reason=f"{reason} | By {interaction.user}")
    await interaction.response.send_message(f"🔨 Banned **{member}** — {reason}")
    if interaction.guild: await log_event(interaction.guild, f"🔨 {member} banned by {interaction.user.mention}: {reason}")


@bot.tree.command(name="timeout", description="Timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
    await member.timeout(timedelta(minutes=minutes), reason=f"{reason} | By {interaction.user}")
    await interaction.response.send_message(f"⏳ Timed out **{member}** for **{minutes} min** — {reason}")


@bot.tree.command(name="userinfo", description="Show information about a member")
async def userinfo(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    if not isinstance(member, discord.Member):
        return await interaction.response.send_message("Server only.", ephemeral=True)
    em = quantix_embed(f"User Info • {member}")
    em.set_thumbnail(url=member.display_avatar.url)
    em.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, style="R"))
    em.add_field(name="Joined server", value=discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "Unknown")
    em.add_field(name="Top role", value=member.top_role.mention)
    await interaction.response.send_message(embed=em)


@bot.tree.command(name="serverinfo", description="Show Quantix server information")
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    if not g:
        return await interaction.response.send_message("Server only.", ephemeral=True)
    em = quantix_embed(f"{g.name} • Server Info")
    if g.icon: em.set_thumbnail(url=g.icon.url)
    em.add_field(name="Members", value=str(g.member_count))
    em.add_field(name="Channels", value=str(len(g.channels)))
    em.add_field(name="Roles", value=str(len(g.roles)))
    em.add_field(name="Created", value=discord.utils.format_dt(g.created_at, style="R"))
    await interaction.response.send_message(embed=em)


@bot.tree.command(name="giveaway", description="Start a Quantix giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(interaction: discord.Interaction, prize: str, minutes: app_commands.Range[int, 1, 10080], channel: Optional[discord.TextChannel] = None):
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        return await interaction.response.send_message("Choose a text channel.", ephemeral=True)
    view = GiveawayView()
    ends = discord.utils.utcnow() + timedelta(minutes=minutes)
    em = quantix_embed("🎉 Quantix Giveaway", f"**Prize:** {prize}\n**Ends:** {discord.utils.format_dt(ends, style='R')}\n\nClick below to enter!")
    msg = await target.send(embed=em, view=view)
    con = db(); con.execute("INSERT OR REPLACE INTO giveaways(message_id,channel_id,prize,ended) VALUES(?,?,?,0)", (msg.id,target.id,prize)); con.commit(); con.close()
    await interaction.response.send_message("Giveaway started ✅", ephemeral=True)

    await asyncio.sleep(minutes * 60)
    if view.users:
        winner_id = random.choice(list(view.users))
        await target.send(f"🎉 Congratulations <@{winner_id}>! You won **{prize}**!")
    else:
        await target.send(f"Giveaway for **{prize}** ended with no entries.")
    con = db(); con.execute("UPDATE giveaways SET ended=1 WHERE message_id=?", (msg.id,)); con.commit(); con.close()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ You don't have permission to use that command."
    else:
        msg = f"❌ Something went wrong: `{str(error)[:180]}`"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    init_db()
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN. Copy .env.example to .env and add your token.")
    bot.run(TOKEN)
