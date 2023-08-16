import sqlite3
import Levenshtein
import pyarabic.araby as araby
from bidi.algorithm import get_display
import speech_recognition as sr
import tkinter as tk
from tkinter import scrolledtext
import re
from speech_recognition import WaitTimeoutError

# For teleprompter
text_area = None
root = tk.Tk()
root.title("Teleprompter")
text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Helvetica", 14))
text_area.pack(expand=True, fill="both")

# For Quran db
db_path = "c:/Users/mohda/Desktop/UW/Spring 2023/ReciFlow/your_database.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT Chapter, Verse, Text FROM verses")
rows = cursor.fetchall()
conn.close()

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


def run_transcription(recognizer, source):
    print("Recite...")

    with sr.Microphone() as source:

        while True:
            try:
                audio = recognizer.listen(source, timeout=1)  # 1 seconds timeout
                transcription = recognizer.recognize_google(audio, language="ar-SA")
                if transcription:
                    return transcription
            except sr.UnknownValueError:
                transcription="UV ERROR"
                pass  # Continue listening if no speech is detected
            except WaitTimeoutError:
                transcription="TIME ERROR"
                print()
                break  # Break the loop on timeout

    return transcription


def update_teleprompter(current_verse, remaining_verses):
    global text_area  # Declare text_area as a global variable
    
    text_area.delete("1.0", tk.END)
    current_verse += 1
    print("current_verse:", current_verse)

    arabic_font = ("Arial", 16)  # Replace with an Arabic-supporting font and appropriate size

    for index, (verse_number, verse_text) in enumerate(remaining_verses):
        if verse_number == current_verse:  # Check if the current verse matches the recognized verse
            text_area.insert(tk.END, f"Verse {verse_number}: {verse_text}\n\n", "red_larger")  # Apply red and larger style
        else:
            text_area.insert(tk.END, f"Verse {verse_number}: {verse_text}\n\n", "normal_arabic")  # Use the Arabic font style
    
    text_area.tag_configure("red_larger", font=("Helvetica", 20, "bold"), foreground="red")  # Define the red and larger style
    text_area.tag_configure("normal_arabic", font=arabic_font)  # Define the Arabic font style
    text_area.yview_moveto(1)  # Automatically scroll down
    text_area.update()







def main():
    # Start the transcription thread for live transcription
    transcription_recognizer = sr.Recognizer()

    similarity_threshold = 0.333
    min_recognized_text_length = 10

    while True:

        with sr.Microphone() as transcription_source:

            recognized_text = run_transcription(transcription_recognizer, transcription_source)
            
            if recognized_text == "UV ERROR":  # Handling recognition error in the beginning
                print("Audio recognition error")
                print()
                continue

            elif recognized_text == "TIME ERROR":  # Handling recognition error in the beginning
                break

            recognized_text = remove_bismillah(recognized_text)

            try:
                if len(recognized_text) < min_recognized_text_length:
                    print("Recognized text length is less than {}, continuing recording...".format(min_recognized_text_length))
                    continue

                best_verse_info, highest_similarity = match_verse(recognized_text, rows)
                
                if highest_similarity < similarity_threshold:
                    print("Similarity below threshold, extending recording...")
                    continue

                if need_to_repeat == True:
                    print("Found similar verses, extending recording...")
                    continue
                    
                else:
                    break
                
            except:
                print("Error in recording initial verse.")
                break
        
    if isinstance(best_verse_info, tuple):
        best_chapter, best_verse = best_verse_info[:2]
    else:
        best_chapter, best_verse = best_verse_info, None
    
    recognized_verse_number = best_verse_info[-1]  # Get the recognized verse number from best_verse_info

    if best_chapter and best_verse:
        remaining_verses = [(verse[1], verse[2]) for verse in rows if verse[0] == best_chapter and verse[1] >= best_verse]
    else:
        remaining_verses = []




    # POST MATCHING

    match_threshold = 0.5  # Matching similarity threshold
    i=0
    
    print("remaining_verses ", remaining_verses)
    print()
    print("remaining_verses[-1][0]", remaining_verses[-1][0])

    while recognized_verse_number < remaining_verses[-1][0]:
        print("recognized_verse_number", recognized_verse_number)
        verse_number, verse_text = remaining_verses[i]
        i+=1
        print("HERE 1")

        for verse_number, verse_text in remaining_verses:
            update_teleprompter(recognized_verse_number, remaining_verses)
            root.update()  # Update the Tkinter window to show the verse
            print("HERE 2")

            while True:
                recognized_text = run_transcription(transcription_recognizer, transcription_source)

                if "UV ERROR" in recognized_text or "TIME ERROR" in recognized_text:
                    print("Audio recognition error")
                    print()
                    continue

                best_verse_info, highest_similarity = match_verse(recognized_text, rows)
                    
                if highest_similarity < match_threshold:
                    print("Similarity below threshold, extending recording...")
                    continue
                
                recognized_verse_number += 1  # Move to the next verse

                break
            

    root.mainloop()
    print("All remaining verses have been processed.")
    
root.destroy()  # Close the teleprompter window


if __name__ == "__main__":
    main()
