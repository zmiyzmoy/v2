import os
import json
import logging
import requests
from fastapi import FastAPI, Request
from telegram import Update, Bot
from telegram.ext import CommandHandler, MessageHandler, filters, ApplicationBuilder, CallbackContext

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация FastAPI
app = FastAPI()

# Получение токена из переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # This is the n8n webhook

# Инициализация бота
# bot = Bot(token=TELEGRAM_BOT_TOKEN) # Bot initialization might not be needed here if not directly used by FastAPI app

@app.post("/webhook") # This is if Telegram sends updates to this bot's webhook
async def webhook_handler(request: Request):
    # This endpoint is if Telegram itself POSTs to this bot.
    # However, the current logic in process_update seems to be for when this bot *receives* a command
    # and then *posts* to n8n.
    # The issue description's docker-compose sets up this bot to receive commands,
    # and its main.py sends messages to n8n's /webhook/general.
    # It doesn't seem to set up a webhook *for* Telegram to call this bot.
    # The provided main.py doesn't seem to use this /webhook endpoint itself.
    # Let's keep it as per the issue, but note this observation.
    update_data = await request.json()
    # update = Update.de_json(update_data, bot) # Needs bot instance
    # await process_update(update) # process_update is not defined in this snippet
    logger.info(f"Received webhook call on telegram_bot_service/webhook: {update_data}")
    return {"status": "ok_from_telegram_bot_webhook"}

# The issue's main.py doesn't have a process_update function,
# nor does it seem to set up handlers for the python-telegram-bot ApplicationBuilder.
# The primary function of the provided main.py is to *send* data to n8n.
# It appears the provided main.py is incomplete or simplified for the purpose of the issue description.
# The crucial part is that it needs to be a running FastAPI service as per docker-compose.
# The issue's python code for main.py looks more like a script that would be triggered,
# rather than a continuously running service that defines how to handle incoming Telegram messages via PTB handlers.

# Let's use the FastAPI structure from the issue, but acknowledge the Telethon/PTB parts are simplified.
# The key is that it should POST to WEBHOOK_URL (n8n).
# The example in the issue for main.py seems to be a mix of a webhook receiver and a message sender.
# For the purpose of this task, I will create the main.py as described in the issue,
# focusing on the FastAPI app and its startup.
# The actual bot logic (receiving from Telegram and then POSTing to n8n)
# would typically involve setting up ApplicationBuilder with handlers.

# Re-evaluating the provided main.py:
# It sets up a FastAPI app. It has a /webhook endpoint.
# It has a startup event.
# The process_update function IS defined in the issue, but it's outside the FastAPI app scope in the example.
# Let's put it inside or make it callable.
# The example also doesn't use ApplicationBuilder correctly within a FastAPI app for receiving messages.
# The most straightforward interpretation is that this service will *not* receive webhooks from Telegram directly.
# Instead, it's likely meant to be a service that *n8n can call* if needed, or it's a placeholder.
# OR, it's a very simplified polling bot that runs via uvicorn.

# Given the docker-compose, it's a service. Let's use the provided code:
_bot_instance = Bot(token=TELEGRAM_BOT_TOKEN) # Make bot instance available

async def process_telegram_update(update: Update, context: CallbackContext): # Renamed to avoid conflict if any
   if update.message and update.message.text:
       user_id = update.effective_user.id
       username = update.effective_user.username
       chat_id = update.effective_chat.id
       message_text = update.message.text
       
       # Определяем username бота для формирования 'to' адреса
       # bot_username = context.bot.username # This would be ideal
       # For now, let's assume the bot's username might need to be configured or derived
       # The issue example uses bot.username which implies the bot instance is part of context or global
       
       bot_identity = await _bot_instance.get_me()
       bot_username = bot_identity.username

       payload = {
           "platform": "telegram",
           "message": {
               "from": f"telegram:{user_id}", # Corrected: user_id is already a string/int
               "to": f"telegram:@{bot_username}", # Use fetched bot username
               "body": message_text,
               "chat_id": chat_id,
               "username": username
           }
       }
       
       try:
           response = requests.post(WEBHOOK_URL, json=payload)
           logger.info(f"Sent to n8n: {json.dumps(payload)}, Response: {response.status_code}")
       except Exception as e:
           logger.error(f"Error sending to n8n: {e}")
           await _bot_instance.send_message(chat_id=chat_id, text="Извините, произошла ошибка. Попробуйте позже.")

# To make this work with FastAPI and uvicorn as per docker-compose,
# we need to run the python-telegram-bot application in a separate thread or asyncio task
# or use its webhook integration. The provided code is a bit mixed.
# The simplest interpretation for the DEMO is that n8n calls this service, or it's a simplified setup.
# However, the `process_telegram_update` logic is what would send to n8n.

# For the FastAPI app as described:
@app.post("/internal_webhook_telegram") # Naming it differently to avoid confusion
async def internal_webhook_telegram(request: Request):
   update_data = await request.json()
   update = Update.de_json(update_data, _bot_instance)
   # Assuming context is not strictly needed for this simplified process_telegram_update
   await process_telegram_update(update, CallbackContext(application=None)) # Dummy context
   return {"status": "ok"}

@app.on_event("startup")
async def startup():
   logger.info(f"Starting Telegram bot service for bot token: {TELEGRAM_BOT_TOKEN[:10]}...")
   # If this service were to receive messages from Telegram via webhook:
   # await _bot_instance.set_webhook(url=f"{YOUR_PUBLIC_URL_FOR_THIS_SERVICE}/internal_webhook_telegram")
   # logger.info("Telegram webhook set.")
   # Or if it's a polling bot (less likely in a docker-compose service like this for prod):
   # application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
   # application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_telegram_update))
   # asyncio.create_task(application.run_polling())
   # logger.info("Telegram bot started polling...")
   pass # For now, just log startup. The actual message sending to n8n will be via process_telegram_update.

if __name__ == "__main__":
   import uvicorn
   # This part is for local execution, Docker will use the CMD in Dockerfile
   uvicorn.run(app, host="0.0.0.0", port=8002)
