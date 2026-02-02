# Telegram to YouTube Upload Bot

A Telegram bot that allows you to upload videos to YouTube directly from Telegram, Google Drive, or any direct link.

## Features

- 📤 Upload videos to YouTube directly from Telegram
- 🔗 Support for multiple sources: Telegram files, direct links, Google Drive, etc.
- 🔐 Secure OAuth 2.0 authentication
- 📊 Real-time upload progress
- 🚀 Bulk upload support
- 💾 Resume uploads for large files
- 👑 Admin-only access control

## Prerequisites

1. **Telegram Bot Token** from [@BotFather](https://t.me/BotFather)
2. **YouTube API Credentials** from [Google Cloud Console](https://console.cloud.google.com/)
3. **Render Account** for deployment

## Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable YouTube Data API v3
4. Create OAuth 2.0 credentials (Web Application)
5. Add authorized redirect URI: `https://your-app.onrender.com/callback`
6. Add your email as a test user

## Local Development

1. Clone the repository:
```bash
git clone https://github.com/yourusername/telegram-youtube-bot.git
cd telegram-youtube-bot