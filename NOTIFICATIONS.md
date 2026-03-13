# 📱 How to Monitor Your Bot on Your Phone (Telegram)

Since you want to monitor your trades while your laptop is off (and the bot is running on a VPS), the best way is to use **Telegram Notifications**.

The bot will send a message to your phone whenever it:
- Opens a new trade 🚀
- Closes a trade (Take Profit or Stop Loss) ✅/❌

## Setup Steps (Takes 2 minutes)

### 1. Create a Telegram Bot
1. Open Telegram on your phone or computer.
2. Search for **@BotFather**.
3. Click **Start** and send the message `/newbot`.
4. Follow the instructions:
   - Name: `MyTradingBot` (or anything you like).
   - Username: `MyUniqueTradingBot_bot` (must end in `_bot`).
5. **BotFather** will give you an **API Token**.
   - It looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
   - **Copy this Token.**

### 2. Get Your Chat ID
1. Search for **@userinfobot** on Telegram.
2. Click **Start**.
3. It will reply with your **Id**.
   - It looks like: `987654321`
   - **Copy this ID.**

### 3. Add to Your Configuration
1. Open the `.env` file in your project folder.
2. Add these two lines at the bottom:

```ini
TELEGRAM_BOT_TOKEN=paste_your_token_here
TELEGRAM_CHAT_ID=paste_your_id_here
```

### 4. Restart the Bot
- Close the black window.
- Double-click `start_bot.bat` again.

---

### 🎉 Done!
Now, even if you are at the beach and your laptop is off, your phone will buzz when the bot makes money on the VPS.
