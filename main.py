import os
import logging
import requests
import json
import asyncio
from dotenv import load_dotenv
import imageio_ffmpeg
import subprocess
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from twilio.rest import Client

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# State definitions for ConversationHandler
ASK_NAME, ASK_BLOOD_TYPE, ASK_URGENCY, ASK_VOICE, ASK_LOCATION = range(5)

# Load Twilio config
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
MY_PHONE_NUMBER = os.getenv('MY_PHONE_NUMBER') # verified number for demo

async def start_sos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the SOS conversation."""
    await update.message.reply_text(
        "🩸 *BloodRadar SOS*\n\n"
        "I will help you find blood urgently. What is your name?",
        parse_mode='Markdown'
    )
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the name and asks for blood type."""
    context.user_data['name'] = update.message.text
    
    reply_keyboard = [['A+', 'A-'], ['B+', 'B-'], ['O+', 'O-'], ['AB+', 'AB-']]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        f"Thanks {context.user_data['name']}. What blood type do you need?",
        reply_markup=markup
    )
    return ASK_BLOOD_TYPE

async def ask_blood_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores blood type and asks for urgency."""
    context.user_data['blood_type'] = update.message.text
    
    reply_keyboard = [['Critical', 'Moderate', 'Planning ahead']]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        "Got it. How urgent is this request?",
        reply_markup=markup
    )
    return ASK_URGENCY

async def ask_urgency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores urgency and asks for a voice message."""
    context.user_data['urgency'] = update.message.text
    
    await update.message.reply_text(
        "Understood. Please record a short voice message (hold the microphone button) explaining your situation. We will play this directly to the hospital."
    )
    return ASK_VOICE

async def receive_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Downloads the voice message, converts it to MP3, uploads to get URL, and asks for location."""
    voice_file = await update.message.voice.get_file()
    
    ogg_path = f"voice_{update.message.message_id}.ogg"
    wav_path = f"voice_{update.message.message_id}.wav"
    await voice_file.download_to_drive(ogg_path)
    
    await update.message.reply_text("🔄 Processing your voice message for perfect phone quality...")
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg_exe, '-i', ogg_path, '-ac', '1', '-ar', '8000', '-c:a', 'pcm_s16le', wav_path, '-y'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    with open(wav_path, 'rb') as f:
        msg = await update.message.reply_document(document=f, filename="voice.wav", caption="Your audio is ready to be played to the hospital.")
        
    audio_file = await context.bot.get_file(msg.document.file_id)
    context.user_data['voice_url'] = audio_file.file_path
    
    os.remove(ogg_path)
    os.remove(wav_path)
    
    location_button = KeyboardButton(text="📍 Share Live Location", request_location=True)
    markup = ReplyKeyboardMarkup([[location_button]], one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        "Perfect. Now please share your Location using the button below to find nearest hospitals.",
        reply_markup=markup
    )
    return ASK_LOCATION

async def receive_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives location, finds hospitals, triggers calls."""
    user_location = update.message.location
    context.user_data['location'] = (user_location.latitude, user_location.longitude)
    
    # Remove keyboard
    await update.message.reply_text(
        "📍 Location received. Scanning for nearby hospitals...",
        reply_markup=ReplyKeyboardRemove()
    )
    
    hospitals = get_nearby_hospitals(user_location.latitude, user_location.longitude)
    
    if not hospitals:
        await update.message.reply_text("I couldn't find any hospitals within 10km. Please try again later.")
        return ConversationHandler.END
        
    context.user_data['hospitals'] = hospitals
    
    await update.message.reply_text(
        f"🏥 Found {len(hospitals)} hospitals nearby.\n\n"
        "Initiating urgent auto-calls to check blood availability..."
    )
    
    # Trigger Twilio Calls (mocking the destination number to be MY_PHONE_NUMBER for demo purposes)
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER and MY_PHONE_NUMBER:
        try:
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            for idx, hospital in enumerate(hospitals):
                # We use Twilio's TwiML to speak a message. 
                voice_url = context.user_data.get('voice_url')
                twiml_script = f"""
                <Response>
                    <Say voice="Polly.Joanna-Neural">
                        Urgent message from Blood Radar! 
                        A patient named {context.user_data['name']} critically needs {context.user_data['blood_type']} blood. 
                        We are calling {hospital['name']}. Here is a voice message from the patient:
                    </Say>
                    <Play>{voice_url}</Play>
                    <Say voice="Polly.Joanna-Neural">
                        Please check your blood bank inventory immediately.
                    </Say>
                </Response>
                """
                call = client.calls.create(
                    twiml=twiml_script,
                    to=MY_PHONE_NUMBER, # Call the verified demo number
                    from_=TWILIO_PHONE_NUMBER
                )
                logger.info(f"Triggered call to {hospital['name']} (SID: {call.sid})")
        except Exception as e:
            logger.error(f"Failed to trigger Twilio call: {e}")
            await update.message.reply_text("⚠️ Note: Twilio auto-calls failed due to configuration issues.")
    else:
         await update.message.reply_text("⚠️ Note: Twilio credentials not fully set up. Skipping actual phone calls for demo.")
         
    # Send the options to the user
    keyboard = []
    message_text = "🏥 Here are the hospitals we contacted. Which one confirmed they have your blood type? Tap to Accept ✅\n\n"
    
    for idx, hospital in enumerate(hospitals):
        dist_km = hospital.get('distance', 0)
        message_text += f"{idx+1}. {hospital['name']} — {dist_km:.1f}km\n"
        keyboard.append([InlineKeyboardButton(f"✅ Accept {hospital['name']}", callback_data=str(idx))])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message_text, reply_markup=reply_markup)
    
    return ConversationHandler.END

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    await query.answer()
    
    selected_idx = int(query.data)
    hospitals = context.user_data.get('hospitals', [])
    
    if not hospitals or selected_idx >= len(hospitals):
        await query.edit_message_text(text="Session expired. Please type /sos again.")
        return
        
    selected_hospital = hospitals[selected_idx]
    
    lat = selected_hospital.get('lat')
    lon = selected_hospital.get('lon')
    maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    
    text = (
        f"✅ Confirmed — {selected_hospital['name']}\n"
        f"📍 Address: {selected_hospital.get('address', 'Address not available')}\n"
        f"📞 Phone: {selected_hospital.get('phone', 'Phone not available')}\n"
        f"🗺️ [Google Maps Link]({maps_link})"
    )
    
    await query.edit_message_text(text=text, parse_mode='Markdown', disable_web_page_preview=True)

def get_nearby_hospitals(lat: float, lon: float, radius: int = 15000) -> list:
    """Queries OpenStreetMap Overpass API for hospitals within `radius` meters."""
    overpass_url = "https://overpass-api.de/api/interpreter"
    overpass_query = f"""[out:json][timeout:25];
node["amenity"="hospital"](around:{radius},{lat},{lon});
out;"""
    hospitals = []
    try:
        headers = {'User-Agent': 'BloodRadarBot/1.0'}
        response = requests.post(overpass_url, data=overpass_query.encode('utf-8'), headers=headers)
        data = response.json()
        
        for element in data.get('elements', []):
            tags = element.get('tags', {})
            name = tags.get('name', 'Unknown Hospital')
            
            # Filter out hospitals without names just to be clean
            if name == 'Unknown Hospital':
                continue
                
            hospitals.append({
                'name': name,
                'lat': element.get('lat'),
                'lon': element.get('lon'),
                'address': tags.get('addr:full', tags.get('addr:street', 'Address unknown')),
                'phone': tags.get('phone', 'Phone unknown'),
                # Very rough pseudo-distance for demo sorting
                'distance': abs(element.get('lat') - lat)*111 + abs(element.get('lon') - lon)*111
            })
            
            if len(hospitals) >= 3:
                break
                
        # Sort by pseudo distance
        hospitals = sorted(hospitals, key=lambda x: x['distance'])
    except Exception as e:
        logger.error(f"Error fetching from Overpass: {e}")

    # Fallback for hackathon demo so it never fails!
    if not hospitals:
        logger.info("No hospitals found via OSM. Falling back to mocked demo data.")
        hospitals = [
            {'name': 'Apollo Hospitals', 'lat': lat + 0.02, 'lon': lon + 0.02, 'address': 'Main City Center', 'phone': '+91-44-12345678', 'distance': 2.3},
            {'name': 'MIOT International', 'lat': lat - 0.03, 'lon': lon + 0.01, 'address': 'Mount Poonamallee Road', 'phone': '+91-44-87654321', 'distance': 4.1},
            {'name': 'Fortis Malar Hospital', 'lat': lat + 0.05, 'lon': lon - 0.04, 'address': 'Gandhi Nagar', 'phone': '+91-44-11223344', 'distance': 6.8}
        ]
        
    return hospitals

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        logger.error("Please set TELEGRAM_BOT_TOKEN in .env")
        return
        
    application = (
        ApplicationBuilder()
        .token(token)
        .connect_timeout(60.0)
        .read_timeout(60.0)
        .write_timeout(60.0)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('sos', start_sos)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_BLOOD_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_blood_type)],
            ASK_URGENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_urgency)],
            ASK_VOICE: [MessageHandler(filters.VOICE, receive_voice)],
            ASK_LOCATION: [MessageHandler(filters.LOCATION, receive_location)],
        },
        fallbacks=[]
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_callback))

    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    main()
