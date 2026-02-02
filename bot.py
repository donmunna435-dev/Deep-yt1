import os
import logging
import tempfile
import asyncio
from urllib.parse import urlparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.ext import CallbackQueryHandler
import requests
import yt_dlp
from config import Config
from youtube_uploader import YouTubeUploader

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize uploader
uploader = YouTubeUploader()

# Store user states
user_states = {}

async def start(update: Update, context: CallbackContext):
    """Send a welcome message when the command /start is issued."""
    user_id = update.effective_user.id
    
    # Check if user is admin
    is_admin = user_id in Config.ADMIN_IDS
    
    welcome_text = f"""
    🎬 *YouTube Upload Bot*
    
    Welcome! I can help you upload videos to YouTube directly from Telegram.
    
    📋 *Available Commands:*
    /start - Show this message
    /auth - Authenticate with YouTube
    /status - Check upload status
    /upload - Upload a video
    
    📁 *Supported Sources:*
    • Telegram files
    • Direct video links
    • Google Drive links
    • Many other cloud services
    
    ⚠️ *Note:* Only admins can use this bot.
    """
    
    if not is_admin:
        welcome_text += "\n\n❌ *Access Denied:* You are not authorized to use this bot."
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
        return
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def auth_command(update: Update, context: CallbackContext):
    """Handle /auth command - Start OAuth flow"""
    user_id = update.effective_user.id
    
    if user_id not in Config.ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    if uploader.is_authenticated(user_id):
        await update.message.reply_text("✅ You are already authenticated!")
        return
    
    # Get OAuth URL
    auth_url = uploader.get_oauth_url(user_id)
    
    # Send auth URL to user
    keyboard = [[InlineKeyboardButton("🔗 Authorize with YouTube", url=auth_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔐 *Authentication Required*\n\n"
        "1. Click the button below to authorize\n"
        "2. You'll be redirected to Google\n"
        "3. After authorization, you'll get a code\n"
        "4. Send that code back to me",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    user_states[user_id] = 'awaiting_auth_code'

async def handle_auth_code(update: Update, context: CallbackContext):
    """Handle authentication code from user"""
    user_id = update.effective_user.id
    
    if user_states.get(user_id) != 'awaiting_auth_code':
        return
    
    auth_code = update.message.text.strip()
    
    try:
        # Construct the full redirect URL with code
        redirect_url = f"{Config.YOUTUBE_REDIRECT_URI}?code={auth_code}"
        
        success = uploader.handle_callback(user_id, redirect_url)
        
        if success:
            await update.message.reply_text("✅ Authentication successful! You can now upload videos.")
            del user_states[user_id]
        else:
            await update.message.reply_text("❌ Authentication failed. Please try /auth again.")
    
    except Exception as e:
        logger.error(f"Auth error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def status_command(update: Update, context: CallbackContext):
    """Handle /status command - Show upload status"""
    user_id = update.effective_user.id
    
    if user_id not in Config.ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    status = uploader.get_upload_status(user_id)
    
    if status['status'] == 'no_uploads':
        await update.message.reply_text("📊 No active uploads.")
    elif status['status'] == 'uploading':
        progress_bar = "▓" * (status['progress'] // 10) + "░" * (10 - status['progress'] // 10)
        await update.message.reply_text(
            f"📤 *Uploading:* {status['file']}\n"
            f"📊 *Progress:* {status['progress']}%\n"
            f"{progress_bar}",
            parse_mode='Markdown'
        )
    elif status['status'] == 'completed':
        video_url = f"https://youtube.com/watch?v={status['video_id']}"
        await update.message.reply_text(
            f"✅ *Upload Complete!*\n"
            f"📹 Video: {video_url}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ Error: {status['status']}")

async def upload_command(update: Update, context: CallbackContext):
    """Handle /upload command - Start upload process"""
    user_id = update.effective_user.id
    
    if user_id not in Config.ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    if not uploader.is_authenticated(user_id):
        await update.message.reply_text("❌ Please authenticate first using /auth")
        return
    
    await update.message.reply_text(
        "📤 *Upload Instructions*\n\n"
        "Send me a video file or a direct link to a video.\n"
        "Supported sources:\n"
        "• Telegram video files\n"
        "• Direct video URLs\n"
        "• Google Drive links\n"
        "• YouTube links (for reupload)\n"
        "• Many cloud storage services",
        parse_mode='Markdown'
    )
    
    user_states[user_id] = 'awaiting_upload'

def download_file(url, destination):
    """Download file from URL with progress"""
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    
    with open(destination, 'wb') as f:
        downloaded = 0
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
    
    return destination

def download_with_ytdlp(url, destination):
    """Download using yt-dlp for various sites"""
    ydl_opts = {
        'outtmpl': destination,
        'format': 'best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return info.get('title', 'video')

async def handle_video_file(update: Update, context: CallbackContext):
    """Handle video file upload"""
    user_id = update.effective_user.id
    
    if user_states.get(user_id) != 'awaiting_upload':
        return
    
    if not update.message.video and not update.message.document:
        await update.message.reply_text("❌ Please send a video file.")
        return
    
    # Get the file
    if update.message.video:
        file = update.message.video
    else:
        file = update.message.document
    
    # Check file size
    if file.file_size > Config.MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ File too large. Max size: {Config.MAX_FILE_SIZE // (1024*1024*1024)}GB")
        return
    
    await update.message.reply_text("⬇️ Downloading file...")
    
    # Download file
    try:
        temp_dir = Config.TEMP_DIR
        os.makedirs(temp_dir, exist_ok=True)
        
        file_obj = await file.get_file()
        file_path = os.path.join(temp_dir, f"{user_id}_{file.file_id}.mp4")
        
        await file_obj.download_to_drive(file_path)
        
        # Ask for video details
        await update.message.reply_text(
            "📝 *Please provide video details*\n\n"
            "Send title and description in this format:\n"
            "`Title: Your Video Title\n"
            "Description: Your video description`\n\n"
            "Add optional tags like:\n"
            "`Tags: tag1, tag2, tag3`",
            parse_mode='Markdown'
        )
        
        context.user_data['file_path'] = file_path
        user_states[user_id] = 'awaiting_video_details'
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        await update.message.reply_text(f"❌ Download failed: {str(e)}")

async def handle_video_link(update: Update, context: CallbackContext):
    """Handle video link upload"""
    user_id = update.effective_user.id
    
    if user_states.get(user_id) != 'awaiting_upload':
        return
    
    url = update.message.text.strip()
    
    # Validate URL
    try:
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            raise ValueError("Invalid URL")
    except:
        await update.message.reply_text("❌ Invalid URL. Please send a valid video link.")
        return
    
    await update.message.reply_text("⬇️ Downloading from link...")
    
    try:
        temp_dir = Config.TEMP_DIR
        os.makedirs(temp_dir, exist_ok=True)
        
        file_path = os.path.join(temp_dir, f"{user_id}_link_video.mp4")
        
        # Try direct download first
        try:
            download_file(url, file_path)
        except:
            # Fallback to yt-dlp
            download_with_ytdlp(url, file_path)
        
        # Ask for video details
        await update.message.reply_text(
            "📝 *Please provide video details*\n\n"
            "Send title and description in this format:\n"
            "`Title: Your Video Title\n"
            "Description: Your video description`\n\n"
            "Add optional tags like:\n"
            "`Tags: tag1, tag2, tag3`",
            parse_mode='Markdown'
        )
        
        context.user_data['file_path'] = file_path
        user_states[user_id] = 'awaiting_video_details'
        
    except Exception as e:
        logger.error(f"Link download error: {e}")
        await update.message.reply_text(f"❌ Download failed: {str(e)}")

async def handle_video_details(update: Update, context: CallbackContext):
    """Handle video details input"""
    user_id = update.effective_user.id
    
    if user_states.get(user_id) != 'awaiting_video_details':
        return
    
    text = update.message.text
    lines = text.split('\n')
    
    title = ""
    description = ""
    tags = []
    
    for line in lines:
        if line.lower().startswith('title:'):
            title = line[6:].strip()
        elif line.lower().startswith('description:'):
            description = line[12:].strip()
        elif line.lower().startswith('tags:'):
            tags = [tag.strip() for tag in line[5:].split(',')]
    
    if not title:
        await update.message.reply_text("❌ Title is required. Please send again with Title:")
        return
    
    file_path = context.user_data.get('file_path')
    if not file_path or not os.path.exists(file_path):
        await update.message.reply_text("❌ File not found. Please start over.")
        del user_states[user_id]
        return
    
    await update.message.reply_text("📤 Starting upload to YouTube...")
    
    try:
        # Start upload
        result = uploader.upload_video(
            user_id,
            file_path,
            title,
            description,
            tags
        )
        
        await update.message.reply_text(f"✅ {result}\nUse /status to check progress.")
        
        # Clean up
        del user_states[user_id]
        if 'file_path' in context.user_data:
            del context.user_data['file_path']
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        await update.message.reply_text(f"❌ Upload failed: {str(e)}")
        del user_states[user_id]

async def error_handler(update: Update, context: CallbackContext):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An error occurred. Please try again or contact admin."
        )

# Flask app for OAuth callback
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/callback')
def callback():
    """OAuth callback endpoint"""
    code = request.args.get('code')
    state = request.args.get('state')
    
    if not code:
        return "Error: No authorization code received", 400
    
    return """
    <html>
        <body>
            <h2>Authorization Successful!</h2>
            <p>Copy the code below and send it to the Telegram bot:</p>
            <textarea readonly style="width: 100%; height: 50px; font-family: monospace;">{}</textarea>
            <p>Go back to Telegram and paste this code.</p>
        </body>
    </html>
    """.format(code)

def main():
    """Start the bot"""
    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return
    
    # Create application
    application = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("auth", auth_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("upload", upload_command))
    
    # Message handlers
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_auth_code
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_video_link
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_video_details
    ))
    application.add_handler(MessageHandler(
        filters.VIDEO | filters.Document.VIDEO,
        handle_video_file
    ))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    logger.info("Starting bot...")
    
    if Config.WEBHOOK_URL:
        # Webhook mode for production
        application.run_webhook(
            listen=Config.HOST,
            port=Config.PORT,
            url_path=Config.BOT_TOKEN,
            webhook_url=f"{Config.WEBHOOK_URL}/{Config.BOT_TOKEN}"
        )
    else:
        # Polling mode for development
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('temp_uploads', exist_ok=True)
    os.makedirs('tokens', exist_ok=True)
    os.makedirs('states', exist_ok=True)
    
    # Run both Flask app and bot
    import threading
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(
        target=lambda: app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=False,
            use_reloader=False
        )
    )
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start bot
    main()