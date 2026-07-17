import os
import urllib.parse
import requests
from flask import Flask, request
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-3.1-flash-lite')

app = Flask(__name__)

# Base system prompt for Gemini
SYSTEM_PROMPT = """
You are an urgent emergency AI assistant calling a hospital on behalf of Blood Radar.
A patient named {name} critically needs {blood_type} blood.
You just played a voice note from the patient to the hospital staff.
The hospital staff is now speaking to you. You must answer them briefly, politely, and urgently.
Keep your responses very short (1-2 sentences) so it flows naturally on a phone call.
Your goal is to figure out if they have {blood_type} blood in stock.
If they ask you to wait or hold on while they check the inventory, DO NOT say Goodbye. Tell them you will wait on the line.
Only when they give you a definitive answer (either YES they have it, or NO they don't), you MUST thank them and end your final response with exactly the word "Goodbye."
"""

@app.route('/twilio_start', methods=['GET', 'POST'])
def twilio_start():
    # Extract patient details passed from main.py via URL parameters
    name = request.values.get('name', 'a patient')
    blood_type = request.values.get('blood_type', 'blood')
    voice_url = request.values.get('voice_url', '')
    chat_id = request.values.get('chat_id', '')
    hospital_name = request.values.get('hospital_name', 'a hospital')

    # We use urllib to safely pass the details to the next gather step
    encoded_args = urllib.parse.urlencode({'name': name, 'blood_type': blood_type, 'chat_id': chat_id, 'hospital_name': hospital_name})
    gather_url = f"/twilio_gather?{encoded_args}".replace('&', '&amp;')

    # Initial TwiML script
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">
        Urgent message from Blood Radar! 
        A patient named {name} critically needs {blood_type} blood. 
        Here is a voice message from the patient:
    </Say>
    <Play>{voice_url}</Play>
    <Gather input="speech" action="{gather_url}" method="POST" timeout="8" speechTimeout="auto">
        <Say voice="alice">
            Hello? Are you there? Please tell me if you have {blood_type} blood available.
        </Say>
    </Gather>
</Response>""".strip()
    return twiml, 200, {'Content-Type': 'text/xml'}

@app.route('/twilio_gather', methods=['POST'])
def twilio_gather():
    name = request.values.get('name', 'a patient')
    blood_type = request.values.get('blood_type', 'blood')
    chat_id = request.values.get('chat_id', '')
    hospital_name = request.values.get('hospital_name', 'a hospital')
    
    # What the hospital person actually said
    speech_result = request.values.get('SpeechResult', '')
    
    if not speech_result:
        # If they didn't speak, prompt them again
        encoded_args = urllib.parse.urlencode({'name': name, 'blood_type': blood_type, 'chat_id': chat_id, 'hospital_name': hospital_name})
        gather_url = f"/twilio_gather?{encoded_args}".replace('&', '&amp;')
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech" action="{gather_url}" method="POST" timeout="8" speechTimeout="auto">
        <Say voice="alice">I didn't catch that. Do you have {blood_type} blood available?</Say>
    </Gather>
</Response>""".strip()
        return twiml, 200, {'Content-Type': 'text/xml'}

    try:
        # Generate conversational response with Gemini
        prompt = SYSTEM_PROMPT.format(name=name, blood_type=blood_type)
        response = model.generate_content(f"{prompt}\n\nHospital Staff Said: {speech_result}\n\nAI Response:")
        ai_text = response.text.strip().encode('ascii', 'ignore').decode('ascii').replace('"', '').replace('*', '').replace('&', 'and').replace('<', '').replace('>', '')
    except Exception as e:
        print(f"Gemini API Error: {e}")
        ai_text = "I'm having trouble connecting to my system. I will notify the patient anyway. Goodbye."

    # Send transcript to Telegram
    if chat_id and os.getenv('TELEGRAM_BOT_TOKEN'):
        telegram_url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage"
        msg = f"📞 **Live Call Update from {hospital_name}:**\n\n🗣️ **Hospital:** \"{speech_result}\"\n\n🤖 **AI Reply:** \"{ai_text}\""
        try:
            requests.post(telegram_url, json={'chat_id': chat_id, 'text': msg, 'parse_mode': 'Markdown'})
        except:
            pass

    # Next iteration loop
    encoded_args = urllib.parse.urlencode({'name': name, 'blood_type': blood_type, 'chat_id': chat_id, 'hospital_name': hospital_name})
    gather_url = f"/twilio_gather?{encoded_args}".replace('&', '&amp;')
    
    if "goodbye" in ai_text.lower():
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{ai_text}</Say>
    <Hangup/>
</Response>""".strip()
    else:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech" action="{gather_url}" method="POST" timeout="8" speechTimeout="auto">
        <Say voice="alice">{ai_text}</Say>
    </Gather>
</Response>""".strip()
    
    return twiml, 200, {'Content-Type': 'text/xml'}

if __name__ == '__main__':
    print("Conversational Twilio Server starting on port 5000...")
    app.run(port=5000)
