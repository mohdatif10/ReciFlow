import sqlite3
import Levenshtein
import pyarabic.araby as araby
from bidi.algorithm import get_display
import speech_recognition as sr
import pyaudio
import wave
import re
from speech_recognition import WaitTimeoutError
import threading
import queue

OUTPUT_FILENAME = "output.wav"  # Output file name
# Create a lock and a queue for handling recognized text
recognized_text_lock = threading.Lock()
recognized_text_queue = queue.Queue()

def record_audio(duration):
    CHUNK = 1024  # Number of frames per buffer
    FORMAT = pyaudio.paInt16  # Audio format (16-bit PCM)
    CHANNELS = 1  # Number of audio channels (1 for mono, 2 for stereo)
    RATE = 44100  # Sample rate (samples per second)

    p = pyaudio.PyAudio()

    # Open audio stream
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    print("Recording...")

    frames = []

    # Capture audio data in chunks and store in frames
    for _ in range(0, int(RATE / CHUNK * duration)):
        data = stream.read(CHUNK)
        frames.append(data)

    print("Recording finished.")

    # Close and terminate the audio stream
    stream.stop_stream()
    stream.close()

    p.terminate()

    # Save recorded audio to a WAV file
    with wave.open(OUTPUT_FILENAME, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))

    print(f"Audio saved as {OUTPUT_FILENAME}")

def remove_diacritics(text):
    return araby.strip_harakat(text)

def remove_bismillah(text):
    bismillah_variations = [
        "بِسۡمِ ٱللَّهِ ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ",
        "بسم الله الرحمن الرحيم"
    ]
    alhamdullillah_pattern = r"(ٱلحمد للّه ربّ ٱلعـٰلمين|ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَـٰلَمِينَ|الحمد لله رب العالمين)"
    
    for variation in bismillah_variations:
        if text.startswith(variation):
            after_bismillah = text[len(variation):].strip()
            alhamdullillah_match = re.search(alhamdullillah_pattern, after_bismillah)
            
            if not alhamdullillah_match:
                return after_bismillah
    
    text = araby.strip_harakat(text)  # Remove diacritics
    return text

def recognize_arabic_speech(audio_path):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_path) as source:
        try:
            audio = recognizer.record(source, duration=10)  # Record for 10 seconds initially
            recognized_text = recognizer.recognize_google(audio, language="ar-SA")
        except sr.UnknownValueError:
            print("Speech recognition failed for the first 10 seconds. Extending recording...")
            audio = recognizer.record(source, duration=30)  # Extend recording to 30 seconds
            try:
                recognized_text = recognizer.recognize_google(audio, language="ar-SA")
            except sr.UnknownValueError:
                recognized_text = ""  # Set recognized_text to empty if recognition still fails
            
    return recognized_text

def match_verse(recognized_text, verses):
    global need_to_repeat 
    recognized_text = remove_bismillah(recognized_text)
    recognized_stripped = remove_diacritics(recognized_text)
    print("recognized_stripped:", recognized_stripped)
    
    best_match = None
    highest_similarity = 0
    best_verse_info = None  # Tuple (chapter, verse)

    need_to_repeat = False  # Initialize the variable before checking similarities
    old_similarity=0


    for verse in verses:
        chapter = verse[0]
        verse_number = verse[1]
        verse_text = verse[2]
        verse_stripped = remove_diacritics(verse_text)
        similarity = 1 - Levenshtein.distance(recognized_stripped, verse_stripped) / max(len(recognized_stripped), len(verse_stripped))

        if similarity > highest_similarity:
            best_match = verse_text
            highest_similarity = similarity
            best_verse_info = (chapter, verse_number)
            
        if similarity==highest_similarity:
            if highest_similarity>old_similarity:
                old_similarity=highest_similarity
                need_to_repeat=False
            else:
                need_to_repeat=True

    if highest_similarity < 0.5:
        for i in range(len(verses) - 1):
            concatenated_text = verses[i][2] + " " + verses[i + 1][2]
            concatenated_stripped = remove_diacritics(concatenated_text)
            similarity = 1 - Levenshtein.distance(recognized_stripped, concatenated_stripped) / max(len(recognized_stripped), len(concatenated_stripped))
            
            if similarity > highest_similarity:
                best_match = concatenated_text
                highest_similarity = similarity
                best_verse_info = (verses[i][0], verses[i][1], verses[i + 1][1])

    print("highest_similarity:", highest_similarity)
    print("matched_verse:", remove_diacritics(best_match))
    print("best_verse_info", best_verse_info)
    
    return best_verse_info, highest_similarity


def run_transcription(recognizer, source, transcription_done_event):
    print("Transcription thread started.")
    silence_timeout = 3  # Seconds of silence to end transcription
    silence_duration = 0  # Current duration of silence

    while not transcription_done_event.is_set():
        audio = recognizer.listen(source, timeout=5)  # Listen for 5 second at a time
        try:
            transcription = recognizer.recognize_google(audio, language="ar-SA")
            if transcription:
                with recognized_text_lock:
                    recognized_text_queue.put(transcription)  # Put recognized text into the queue
                print("Transcription in run_trasncription", transcription)
                silence_duration = 0  # Reset silence duration if there's audio
        except sr.UnknownValueError:
            silence_duration += 1
            if silence_duration >= silence_timeout:
                break  # End transcription if silence threshold is reached
        except sr.RequestError as e:
            print("Could not request results; {0}".format(e))
            silence_duration = 0
        except sr.WaitTimeoutError:
                    print("Timeout reached. Ending transcription.")
                    break  # Break the loop on timeout
                
    return transcription


def continue_recitation_match(next_verse_text, expected_verse_text):
    next_verse_stripped = remove_diacritics(next_verse_text)
    expected_verse_stripped = remove_diacritics(expected_verse_text)
    
    similarity = 1 - Levenshtein.distance(next_verse_stripped, expected_verse_stripped) / max(len(next_verse_stripped), len(expected_verse_stripped))
    return similarity >= 0.5



def main():
    initial_record_duration = 6
    extended_record_duration = 10
    similarity_threshold = 0.333
    min_recognized_text_length = 10
    extended_recording_done = False

    while True:
        record_audio_duration = extended_record_duration if extended_recording_done else initial_record_duration
        record_audio(record_audio_duration)
        audio_path = OUTPUT_FILENAME

        try:
            recognized_text = recognize_arabic_speech(audio_path)
            recognized_text = remove_bismillah(recognized_text)

            if len(recognized_text) < min_recognized_text_length:
                print("Recognized text length is less than {}, continuing recording...".format(min_recognized_text_length))
                extended_recording_done = True
                continue

            db_path = "c:/Users/mohda/Desktop/UW/Spring 2023/ReciFlow/your_database.db"
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT Chapter, Verse, Text FROM verses")
            rows = cursor.fetchall()
            conn.close()

            best_verse_info, highest_similarity = match_verse(recognized_text, rows)
            
            if highest_similarity < similarity_threshold:
                if not extended_recording_done:
                    print("Similarity below threshold, extending recording...")
                    extended_recording_done = True
                    continue
                else:
                    print("Extended recording already done, stopping.")
                    break

            if need_to_repeat == True:
                print("Found similar verses, extending recording...")
                extended_recording_done = True
                
            else:
                break
            
        except sr.UnknownValueError:
            if not extended_recording_done:
                print("Speech recognition failed for the first {} seconds. Extending recording...".format(record_audio_duration))
                extended_recording_done = True
            else:
                print("Extended recording already done, stopping.")
                break
        
    if isinstance(best_verse_info, tuple):
        best_chapter, best_verse = best_verse_info[:2]
    else:
        best_chapter, best_verse = best_verse_info, None
    
    if best_chapter and best_verse:
        remaining_verses = [(verse[1], verse[2]) for verse in rows if verse[0] == best_chapter and verse[1] >= best_verse]
    else:
        remaining_verses = []

    remaining_verses=remaining_verses[1:]



    # Now for post-match recitation
   
    print()
    for verse_number, verse_text in remaining_verses:
        print(f"Chapter {best_chapter}, Verse {verse_number}: {verse_text}")

    print()

    for verse_number, verse_text in remaining_verses:
        print(f"Processing Verse {verse_number}: {verse_text}")

        # Start the transcription thread for live transcription
        transcription_done_event = threading.Event()
        transcription_recognizer = sr.Recognizer()

        with sr.Microphone() as transcription_source:
            transcription_thread = threading.Thread(target=run_transcription, args=(transcription_recognizer, transcription_source, transcription_done_event))
            transcription_thread.start()

            print("Started recording")

            match_threshold = 0.5  # Matching similarity threshold

            while True:
                try:
                    # Reuse the run_transcription function here
                    transcription=run_transcription(transcription_recognizer, transcription_source, transcription_done_event)

                    verse_stripped = remove_diacritics(verse_text)
                    similarity = 1 - Levenshtein.distance(remove_diacritics(transcription), verse_stripped) / max(len(transcription), len(verse_stripped))
                    
                    print("Similarity of transcription ", similarity)

                    if similarity >= match_threshold:
                        print("Verse recognized correctly.")
                        break
                    else:
                        print("Wrong recitation. Please try again.")

                except sr.UnknownValueError:
                    pass  # Continue listening if no speech is detected
                except sr.WaitTimeoutError:
                    print("Timeout reached. Ending transcription.")
                    break  # Break the loop on timeout

            print("Transcription thread stopping.")
            transcription_done_event.set()  # Signal the transcription thread to stop
            transcription_thread.join()  # Wait for the transcription thread to finish

    print("All remaining verses have been processed.")

if __name__ == "__main__":
    main()