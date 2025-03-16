# handlers/telegram.py
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config.settings import TELEGRAM_BOT_TOKEN
from agents import SomiAgent

class TelegramHandler:
    def __init__(self):
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.agent = SomiAgent("SomiBot")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Hello! I’m SomiBot. Send me a message!")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        prompt = update.message.text
        response = self.agent.generate_response(prompt)
        await update.message.reply_text(response)

    def run(self):
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        print("Starting Telegram bot...")
        self.application.run_polling()

if __name__ == "__main__":
    handler = TelegramHandler()
    handler.run()