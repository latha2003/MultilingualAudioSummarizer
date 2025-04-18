import streamlit as st
import bcrypt
from pymongo import MongoClient
import speech_recognition as sr
import tempfile
import google.generativeai as generative_ai
from pydub import AudioSegment
from googletrans import Translator
from moviepy import VideoFileClip
from gtts import gTTS 
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import os
import re
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set page config as the first Streamlit command
st.set_page_config(page_title="Audio Summarizer", layout="wide")

# Load environment variables
load_dotenv(".env")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
API_KEY = os.getenv("API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

# Validate environment variables
if not all([EMAIL_ADDRESS, EMAIL_PASSWORD, API_KEY, MONGO_URL]):
    st.error("❌ Missing environment variables. Check '.env' file.")
    st.stop()

# MongoDB setup with error handling
try:
    client = MongoClient(MONGO_URL)
    db = client["audio_summarizer_db"]
    users_collection = db["users"]
    sessions_collection = db["sessions"]
except Exception as e:
    st.error(f"❌ Failed to connect to MongoDB: {e}")
    st.stop()

# Configure Google Generative AI with error handling
try:
    generative_ai.configure(api_key=API_KEY)
except Exception as e:
    st.error(f"❌ Failed to configure Google Generative AI: {e}")
    st.stop()

# Language options
languages = {
    "Telugu": "te-IN", "Hindi": "hi-IN", "English": "en-US", "Spanish": "es",
    "French": "fr", "German": "de", "Portuguese": "pt", "Italian": "it",
    "Japanese": "ja", "Chinese": "zh"
}

# Initialize Session State
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "sessions" not in st.session_state:
    st.session_state.sessions = {}
if "selected_session" not in st.session_state:
    st.session_state.selected_session = None
if "rename_mode" not in st.session_state:
    st.session_state.rename_mode = None
if "file_uploader_key" not in st.session_state:
    st.session_state.file_uploader_key = 0

# Helper Functions
def get_sessions(user_id):
    return {s.get("session_name", str(s["_id"])): s for s in sessions_collection.find({"user_id": user_id})}

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(password, hashed):
    if isinstance(hashed, str):
        hashed = hashed.encode('utf-8')
    return bcrypt.checkpw(password.encode('utf-8'), hashed)

def add_custom_css():
    st.markdown("""
        <style> 
             .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
    font-size:25px;
    padding: 15px 20px
    }   
        </style>
    """, unsafe_allow_html=True)

def send_email(user_email, summary_text):
    if not re.match(r"[^@]+@[^@]+\.[^@]+", user_email):
        st.error("❌ Invalid email address.")
        return
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = user_email
        msg["Subject"] = "Your Audio Summary"
        msg.attach(MIMEText(f"Hello,\n\nHere is your audio summary:\n\n{summary_text}\n\nBest Regards,\nSummarizer App", "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, user_email, msg.as_string())
        server.quit()
        st.success("✅ Email sent successfully!")
    except Exception as e:
        st.error(f"❌ Email failed: {e}")
        logger.error(f"Email sending failed: {e}")

def send_notes_email(user_email, notes):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = user_email
        msg["Subject"] = "Your Notes regarding Audio Summary"
        msg.attach(MIMEText(f"Hello,\n\nHere is your notes:\n\n{notes}\n\nBest Regards,\nSummarizer App", "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, user_email, msg.as_string())
        server.quit()
        st.success("✅ Email sent successfully!")
    except Exception as e:
        st.error(f"❌ Email failed: {e}")

def convert_to_wav(uploaded_file):
    wav_file = None
    try:
        audio = AudioSegment.from_file(uploaded_file)
        wav_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        audio.export(wav_file.name, format="wav")
        return wav_file.name
    except Exception as e:
        st.error(f"❌ Error converting audio: {e}")
        logger.error(f"Audio conversion failed: {e}")
        if wav_file and os.path.exists(wav_file.name):
            os.unlink(wav_file.name)
        return None

def extract_audio_from_video(uploaded_video):
    temp_video_path = None
    wav_file_path = None
    try:
        temp_video = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_video_path = temp_video.name
        temp_video.write(uploaded_video.read())
        temp_video.close()
        video_clip = VideoFileClip(temp_video_path)
        if not video_clip.audio:
            st.error("❌ Video has no audio track.")
            os.unlink(temp_video_path)
            return None
        wav_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        wav_file_path = wav_file.name
        video_clip.audio.write_audiofile(wav_file_path, codec="pcm_s16le")
        video_clip.close()
        os.unlink(temp_video_path)
        return wav_file_path
    except Exception as e:
        st.error(f"❌ Video processing error: {e}")
        logger.error(f"Video processing failed: {e}")
        if temp_video_path and os.path.exists(temp_video_path):
            os.unlink(temp_video_path)
        if wav_file_path and os.path.exists(wav_file_path):
            os.unlink(wav_file_path)
        return None

def transcribe_audio(audio_file, lang_code):
    r = sr.Recognizer()
    try:
        with sr.AudioFile(audio_file) as source:
            audio_data = r.record(source)
        return r.recognize_google(audio_data, language=lang_code)
    except sr.UnknownValueError:
        st.error("❌ Could not understand the audio.")
    except sr.RequestError as e:
        st.error(f"❌ Transcription error: {e}")
        logger.error(f"Transcription failed: {e}")
    finally:
        if os.path.exists(audio_file):
            os.unlink(audio_file)  # Clean up temporary file
    return None

def summarize_text(text, lang_code):
    try:
        model = generative_ai.GenerativeModel("gemini-1.5-flash-001")
        lang_map = {v: k for k, v in languages.items()}
        lang_name = lang_map.get(lang_code, "English")
        response = model.generate_content([f"Give a very short summary of this text in {lang_name}:\n{text}"])
        return response.text
    except Exception as e:
        st.error(f"⚠ Summary generation failed: {e}")
        logger.error(f"Summary generation failed: {e}")
        return "Summary unavailable"

def translate_summary(summary_text, target_lang):
    try:
        translator = Translator()
        return translator.translate(summary_text, dest=target_lang.split('-')[0]).text
    except Exception as e:
        st.error(f"❌ Translation error: {e}")
        logger.error(f"Translation failed: {e}")
        return summary_text

def get_response(question, summary):
    try:
        model = generative_ai.GenerativeModel("gemini-1.5-flash-001")
        response = model.generate_content(f"Based on this summary: '{summary}', answer the question: '{question}'")
        return response.text
    except Exception as e:
        st.error(f"❌ Chatbot API error: {e}")
        logger.error(f"Chatbot API failed: {e}")
        return "Error processing response."

# Sidebar - Account Management
with st.sidebar:
    st.title("Account")
    
    if st.session_state.user_id:
        st.write(f"Logged in as: *{st.session_state.user_id}*")
        if st.button("Logout"):
            st.session_state.user_id = None
            st.session_state.sessions = {}
            st.session_state.selected_session = None
            st.session_state.file_uploader_key += 1
            st.rerun()

        if st.button("➕ Start New Session"):
            user_sessions = list(sessions_collection.find({"user_id": st.session_state.user_id}))
            new_session_number = len(user_sessions) + 1
            new_session_name = f"Session {new_session_number}"
            session_data = {"user_id": st.session_state.user_id, "session_name": new_session_name}
            sessions_collection.insert_one(session_data)
            st.session_state.sessions = get_sessions(st.session_state.user_id)
            st.session_state.selected_session = new_session_name
            st.session_state.file_uploader_key += 1
            st.rerun()
    else:
        option = st.selectbox("Select an option", ["Login", "Create Account", "Forgot Password"])
        if option == "Login":
            user_id = st.text_input("User ID:")
            password = st.text_input("Password:", type="password")
            if st.button("Login"):
                user = users_collection.find_one({"user_id": user_id})
                if user and check_password(password, user["password"]):
                    st.session_state.user_id = user_id
                    st.session_state.sessions = get_sessions(user_id)
                    st.success(f"Welcome back, {user_id}!")
                    st.session_state.selected_session = None
                    st.rerun()
                else:
                    st.error("Invalid credentials!")
        elif option == "Create Account":
            new_user_id = st.text_input("Choose a User ID:")
            new_password = st.text_input("Choose a Password:", type="password")
            confirm_password = st.text_input("Confirm Password:", type="password")
            if st.button("Create Account"):
                if new_password == confirm_password:
                    if users_collection.find_one({"user_id": new_user_id}):
                        st.error("User ID already exists!")
                    else:
                        users_collection.insert_one({"user_id": new_user_id, "password": hash_password(new_password)})
                        st.success("Account created! You can now log in.")
                else:
                    st.error("Passwords do not match!")
        elif option == "Forgot Password":
            user_id = st.text_input("Enter your User ID:")
            new_password = st.text_input("Enter New Password:", type="password")
            confirm_password = st.text_input("Confirm New Password:", type="password")
            if st.button("Reset Password"):
                user = users_collection.find_one({"user_id": user_id})
                if user:
                    if new_password == confirm_password:
                        users_collection.update_one({"user_id": user_id}, {"$set": {"password": hash_password(new_password)}})
                        st.success("Password reset successfully!")
                    else:
                        st.error("Passwords do not match!")
                else:
                    st.error("User ID not found!")

# Sidebar - Session Management
if st.session_state.user_id:
    st.sidebar.title("Sessions")
    st.session_state.sessions = get_sessions(st.session_state.user_id)
    for session_name in sorted(st.session_state.sessions.keys()):
        session_data = st.session_state.sessions[session_name]
        col1, col2, col3 = st.sidebar.columns([4, 1, 1])
        if col1.button(session_name, key=f"session_{session_name}"):
            if st.session_state.selected_session != session_name:
                st.session_state.selected_session = session_name
                st.session_state.file_uploader_key += 1
        if col2.button("✏️", key=f"rename_{session_name}"):
            st.session_state.rename_mode = session_name
        if col3.button("🗑️", key=f"delete_{session_name}"):
            sessions_collection.delete_one({"session_name": session_name, "user_id": st.session_state.user_id})
            st.session_state.sessions = get_sessions(st.session_state.user_id)
            if st.session_state.selected_session == session_name:
                st.session_state.selected_session = None
            st.session_state.file_uploader_key += 1
            st.rerun()

    if st.session_state.rename_mode:
        session_to_rename = st.session_state.rename_mode
        new_name = st.sidebar.text_input(f"Rename '{session_to_rename}' to:", session_to_rename)
        if st.sidebar.button("✅ Save Name"):
            sessions_collection.update_one(
                {"session_name": session_to_rename, "user_id": st.session_state.user_id},
                {"$set": {"session_name": new_name}}
            )
            st.session_state.sessions = get_sessions(st.session_state.user_id)
            st.session_state.selected_session = new_name if st.session_state.selected_session == session_to_rename else st.session_state.selected_session
            st.session_state.rename_mode = None
            st.session_state.file_uploader_key += 1
            st.rerun()

# Main Area - Session Details with Summarizer
if st.session_state.user_id and st.session_state.selected_session:
    session_name = st.session_state.selected_session
    st.title(f"🎤 Multilingual Audio Summarizer - {session_name}")
    session_data = st.session_state.sessions.get(session_name, {})

    # Show language selector and file uploader only if no transcription exists
    if "transcription" not in session_data:
        selected_language = st.selectbox("🔤 Select Language", list(languages.keys()))
        language_code = languages[selected_language]
        uploaded_file = st.file_uploader(
            "📤 Upload audio/video",
            type=["mp3", "wav", "m4a", "flac", "mp4", "avi", "mov"],
            key=f"uploader_{st.session_state.file_uploader_key}"
        )

        # Process file only when "Process File" button is clicked
        if uploaded_file is not None:
            if st.button("🔄 Process File"):
                st.write("🔄 Processing file...")
                file_type = uploaded_file.type
                wav_file_path = None
                filename = uploaded_file.name  # Capture the filename

                if file_type.startswith("video"):
                    st.video(uploaded_file)
                    st.write("🎥 Extracting audio from video...")
                    wav_file_path = extract_audio_from_video(uploaded_file)
                elif file_type.startswith("audio"):
                    st.audio(uploaded_file, format=file_type)
                    wav_file_path = convert_to_wav(uploaded_file)

                if wav_file_path:
                    st.write("🔊 Transcribing audio...")
                    transcribed_text = transcribe_audio(wav_file_path, language_code)
                    if transcribed_text:
                        summary = summarize_text(transcribed_text, language_code)
                        # Store filename along with transcription and summary
                        sessions_collection.update_one(
                            {"session_name": session_name, "user_id": st.session_state.user_id},
                            {"$set": {"transcription": transcribed_text, "summary": summary, "filename": filename}},
                            upsert=True
                        )
                        st.session_state.sessions = get_sessions(st.session_state.user_id)
                        st.session_state.file_uploader_key += 1  # Reset uploader after processing
                        st.rerun()  # Refresh to show new content

    # Display session data if available
    if "transcription" in session_data:
        # Show the filename message instead of uploader and language selector
        filename = session_data.get("filename", "unknown file")
        st.subheader(f"Your transcription and summary for *{filename}*")

        st.subheader("📝 Audio Transcript")
        st.write(session_data["transcription"])
        st.success("📄 Summary")
        st.write(session_data["summary"])

        add_custom_css()
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["💬 Chatbot", "🌎 Translate", "📧 Email", "📝 Notes", "🔊 Voice Output"])
        with tab1:
            st.subheader("💬 Ask Questions About the Summary")
            question = st.text_input("❓ Ask a question:")
            if st.button("🧠 Get Answer") and question.strip():
                answer = get_response(question, session_data["summary"])
                st.success("📝 Answer:")
                st.write(answer)
        with tab2:
            additional_lang = st.selectbox("🔄 Choose Language", list(languages.keys()))
            if st.button("🔄 Translate"):
                translated_summary = translate_summary(session_data["summary"], languages[additional_lang])
                st.success(f"📄 Translated Summary in {additional_lang}:")
                st.write(translated_summary)
        with tab3:
            user_email = st.text_input("📧 Enter recipient email:")
            if st.button("📤 Send Email"):
                send_email(user_email, session_data["summary"])
        with tab4:  # Notes tab
            st.subheader("📝 Notes")
            st.session_state.notes = st.text_area("Write your notes here:", st.session_state.get("notes", ""), height=200)
            user_email = st.text_input("Enter email:")
            if st.button("Send Email 📤 "):
                send_notes_email(user_email, st.session_state.notes)
        with tab5:  # Voice Output tab
            st.subheader("🔊 Listen to the Summary")
            if "transcription" in session_data:
                st.write("Click the button below to listen to the summary:")
                tts = gTTS(text=session_data["summary"], lang='en')  # Change lang if needed
                audio_path = "summary_audio.mp3"
                tts.save(audio_path)
                st.audio(audio_path, format="audio/mp3")
            else:
                st.warning("⚠ No summary available. Please generate one first.")

    elif "transcription" not in session_data:
        st.write("No content available for this session yet. Upload a file and click 'Process File' to get started.")
elif not st.session_state.user_id:
    st.title("🎤 Multilingual Audio Summarizer")
    st.markdown("""
        ### Welcome to the **Multilingual Audio Summarizer**! 
        🔹 Convert **audio/video files** into text effortlessly.  
        🔹 Summarize large transcripts into concise, meaningful summaries.  
        🔹 Support for **multiple languages** – select your preferred one!  
        🔹 Integrated features like **Chatbot, Translation, Email, Notes, and Voice Output.**  

        👉 **Log in or create an account to get started!**  
        """, unsafe_allow_html=True)
else:
    st.title("🎤 Multilingual Audio Summarizer")
    st.markdown("""
        ### Welcome to the **Multilingual Audio Summarizer**! 
        🔹 Convert **audio/video files** into text effortlessly.  
        🔹 Summarize large transcripts into concise, meaningful summaries.  
        🔹 Support for **multiple languages** – select your preferred one!  
        🔹 Integrated features like **Chatbot, Translation, Email, Notes, and Voice Output.**  

        👉 **Select a session or create new one to begin**  
        """, unsafe_allow_html=True)