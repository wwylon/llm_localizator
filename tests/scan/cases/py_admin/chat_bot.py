import discord


class BotError(Exception):
    pass


def setup(client):
    @client.tree.command(name="chat", description="Chat in your conversation in this channel")
    async def chat(interaction: discord.Interaction, message: str) -> None:
        if not message:
            raise BotError("Provide a message to send.")
        result = "Request cancelled. Provider work may still be billed."
        await interaction.followup.send(result)


def check(value):
    if value is None:
        raise ValueError("value must not be None")
    return "advertising enable"
