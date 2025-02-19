import streamlit as st
import speech_recognition as sr
import tempfile
import google.generativeai as generative_ai
from pydub import AudioSegment
from googletrans import Translator 

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

EMAIL_ADDRESS = st.secrets["EMAIL_ADDRESS"]
EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

# Configure Gemini API securely
generative_ai.configure(api_key=GEMINI_API_KEY)

def send_email_with_summary(user_email, summary_text):
    """Sends an email with the summarized text."""
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = user_email
        msg["Subject"] = "Your Audio Summary"

        body = f"Hello,\n\nHere is the summary of your audio file:\n\n{summary_text}\n\nBest Regards,\nMultilingual Audio Summarizer"
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, user_email, text)
        server.quit()
        
        st.success("Email sent successfully!")
    except Exception as e:
        st.error(f"Failed to send email: {e}")

def convert_to_wav(uploaded_file):
    """Converts the uploaded audio file to WAV format."""
    try:
        audio = AudioSegment.from_file(uploaded_file)
        wav_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        audio.export(wav_file, format="wav")
        return wav_file.name
    except Exception as e:
        st.error(f"Error converting audio to WAV: {e}")
        return None

def transcribe_audio(audio_file, language_code):
    """Transcribes audio to text using SpeechRecognition."""
    r = sr.Recognizer()
    with sr.AudioFile(audio_file) as source:
        audio_data = r.record(source, duration=None)
    try:
        text = r.recognize_google(audio_data, language=language_code)
        return text
    except sr.UnknownValueError:
        st.error("Google Speech Recognition could not understand the audio.")
    except sr.RequestError as e:
        st.error(f"Google Speech Recognition error: {e}")
    return None

def summarize_text_with_gemini(text, language_code):
    """Summarizes text using Gemini API and translates it."""
    if "summary" in st.session_state:
        return st.session_state.summary  

    try:
        model = generative_ai.GenerativeModel("gemini-1.5-flash-001")
        response = model.generate_content([f"Give very short summary of this text to include important details only:\n{text}"])
        summary = response.text

        #translator = Translator()
        #translated_summary = translator.translate(summary, src='en', dest=language_code.split('-')[0]).text
        
        st.session_state.summary = summary  # Cache summary
        return summary
    except Exception as e:
        st.error("⚠️ API limit reached. Please try again later.")
        return "Summary unavailable due to API limits."


def translate_summary(summary_text, new_language_code):
    """Translates an existing summary into another language."""
    try:
        translator = Translator()
        return translator.translate(summary_text, dest=new_language_code.split('-')[0]).text
    except Exception as e:
        st.error(f"Translation error: {e}")
        return summary_text



def main():
    st.title("🎤 Multilingual Audio Summarizer")

    # Language selection dropdown
    languages = {
        "Telugu": "te-IN",
        "Hindi": "hi-IN",
        "English": "en-US",
        "Spanish": "es",
        "French": "fr",
        "German": "de",
        "Portuguese": "pt",
        "Italian": "it",
        "Japanese": "ja",
        "Chinese": "zh"
    }
    selected_language = st.selectbox("🔤 Select Language for transcription and summary", list(languages.keys()))
    language_code = languages[selected_language]

    uploaded_file = st.file_uploader("📤 Upload audio", type=["mp3", "wav", "m4a", "flac"])

    if uploaded_file is not None and "transcribed_text" not in st.session_state:
        # Convert the uploaded audio file to WAV format
        wav_file_path = convert_to_wav(uploaded_file)

        if wav_file_path:
            st.write("🔊 Transcribing audio...")

            # Perform transcription
            transcribed_text = transcribe_audio(wav_file_path, language_code)
            if transcribed_text:
                st.session_state.transcribed_text = transcribed_text  # Store in session state

    if "transcribed_text" in st.session_state:
        st.write("📝 Audio Transcript")
        st.write(st.session_state.transcribed_text)

        if "summary" not in st.session_state:
            summary = summarize_text_with_gemini(st.session_state.transcribed_text, language_code)
            st.session_state.summary = summary

        st.success("📄 Summary")
        st.write(st.session_state.summary)

        # Email Feature
        user_email = st.text_input("📧 Enter email to send summary:")
        if st.button("📤 Send Email"):
            if user_email:
                send_email_with_summary(user_email, st.session_state.summary)
            else:
                st.error("❌ Please enter a valid email address.")
        

        # Additional Translation Feature
        st.subheader("🌎 Get the Summary in Another Language")
        additional_language = st.selectbox("🔄 Choose another language:", list(languages.keys()))
        additional_language_code = languages[additional_language]

        if st.button("🔄 Translate Summary"):
            translated_summary = translate_summary(st.session_state.summary, additional_language_code)
            st.success(f"📄 **Translated Summary in {additional_language}:**")
            st.write(translated_summary)

if __name__ == "__main__":
    main()
