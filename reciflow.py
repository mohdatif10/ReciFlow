import sqlite3
import pyarabic.araby as araby
from bidi.algorithm import get_display
import speech_recognition as sr
import tkinter as tk
from tkinter import scrolledtext
import re
from speech_recognition import WaitTimeoutError
from fuzzywuzzy import fuzz

iteration_ct = 0 # 2 rakats => 4 loud recitations for each salat
recitation_speed = 0.45 # User choice

# For Quran db
db_path = "c:/Users/mohda/Desktop/UW/Spring 2023/ReciFlow/your_database.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT Chapter, Verse, Text FROM verses")
rows = cursor.fetchmany(10)
conn.close()


def remove_diacritics(text):
    return araby.strip_harakat(text)


def match_verse(recognized_text, verses):
    recognized_stripped = remove_diacritics(recognized_text)

    best_match = None
    highest_similarity = 0
    best_verse_info = None  # Tuple (chapter, verse)

    need_to_repeat = False
    old_similarity = 0

    for verse in verses:
        chapter, verse_number, verse_text = verse
        verse_stripped = remove_diacritics(verse_text)
        similarity = fuzz.ratio(recognized_stripped, verse_stripped) / 100.0

        if similarity > highest_similarity:
            best_match = verse_text
            highest_similarity = similarity
            best_verse_info = (chapter, verse_number)

        if similarity == highest_similarity:
            if highest_similarity > old_similarity:
                old_similarity = highest_similarity
                need_to_repeat = False
            else:
                need_to_repeat = True

    if highest_similarity < 0.43:
        for i in range(len(verses) - 1):
            concatenated_text = verses[i][2] + " " + verses[i + 1][2]
            concatenated_stripped = remove_diacritics(concatenated_text)
            similarity = fuzz.ratio(recognized_stripped, concatenated_stripped) / 100.0

            if similarity > highest_similarity:
                best_match = concatenated_text
                highest_similarity = similarity
                best_verse_info = (verses[i][0], verses[i][1], verses[i + 1][1])

    print("best_verse_info, highest_similarity" , best_verse_info, highest_similarity)

    return best_verse_info, highest_similarity, need_to_repeat


def run_transcription(recognizer, source, remaining_verses=[], next_verse=0, tmo=35, pth=(recitation_speed*4)):
    print()
    print("Recite...")

    if next_verse != 0:
        for chapter, verse_number, verse_text in remaining_verses:
            if verse_number == next_verse:
                pth = len(verse_text.split()) * 0.45 
                break
    
    with sr.Microphone() as source:

        while True:
            try:
                audio = recognizer.listen(source, timeout=tmo, phrase_time_limit=pth)
                transcription = recognizer.recognize_google(audio, language="ar-SA")
                if transcription:
                    return transcription
            except sr.UnknownValueError:
                transcription = "UV ERROR"
                pass  # Continue listening if no speech is detected
            except WaitTimeoutError:
                transcription = "TIME ERROR"
                print()
                break  # Break the loop on timeout

    return transcription


def update_teleprompter(root, text_area, current_verse, remaining_verses, attempts_mismatch):
    arabic_font = ("Amiri", 50)

    # Find and remove the current verse from remaining_verses
    verse_to_remove = None
    for index, (chapter, verse_number, _) in enumerate(remaining_verses):
        if verse_number == current_verse:
            verse_to_remove = index
            break

    if verse_to_remove is not None:
        remaining_verses.pop(0)

    text_area.delete("1.0", tk.END)
    current_verse += 1
    print("current_verse:", current_verse)

    for index, (chapter, verse_number, verse_text) in enumerate(remaining_verses):
        if verse_number == current_verse:
            if attempts_mismatch == 0:
                # Current verse, no mismatch
                text_area.insert(tk.END, f"{chapter}, {verse_number}: {verse_text}\n\n", "red_larger")
            elif attempts_mismatch == 1:
                # Current verse, one mismatch
                text_area.insert(tk.END, f"{chapter}, {verse_number}: {verse_text}\n\n", "blue_larger")
        else:
            # Not the current verse
            text_area.insert(tk.END, f"{chapter}, {verse_number}: {verse_text}\n\n", "normal_arabic")

    # Configure tags for font styles and colors
    text_area.tag_configure("red_larger", font=("Amiri", 80, "bold"), foreground="red")
    text_area.tag_configure("blue_larger", font=("Amiri", 95, "bold"), foreground="blue")
    text_area.tag_configure("normal_arabic", font=arabic_font)

    # Update the Tkinter window and the scrollbar
    text_area.update_idletasks()
    root.update()
   
    


#################################################################################################################################################

def main():
    global iteration_ct
    surah_1=None # User's choice
    surah_2=None # User's choice
    pth=None

    text_area = None
    root = tk.Tk()
    root.attributes('-fullscreen', True)
    root.title("Teleprompter")
    text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Amiri", 50))
    text_area.pack(expand=True, fill="both")

    transcription_recognizer = sr.Recognizer()
    similarity_threshold = 0.25
    min_recognized_text_length = 5

    while True:

        with sr.Microphone() as transcription_source:

            # if (surah_1!=None and iteration_ct==1) or (surah_2!=None and iteration_ct==11):
            #     pth=recitation_speed*


            recognized_text = run_transcription(transcription_recognizer, transcription_source)

            print("recognized_text , ", recognized_text)

            if re.match(r"^بسم الله الرحمن الرحيم\s*$", recognized_text):
                print("Recognized بسم الله الرحمن الرحيم. Continue...")
                continue

            elif re.search(r"(سميع الله لمن حمده|سمى الله لمن حمده|الله اكبر|سمى الله لمن هم)", recognized_text): # امين needs to be reconsidered
                root.destroy() 
                iteration_ct+=1
                print("Detected {}. Prayer action...".format(recognized_text))
                main()
            
            elif recognized_text == "UV ERROR":  # Handling recognition error in the beginning
                print("Audio recognition error")
                print()
                continue

            elif recognized_text == "TIME ERROR":  # Handling recognition error in the beginning
                break

            try:
                if len(recognized_text) < min_recognized_text_length:
                    print("Recognized text length is less than {}, continuing recording...".format(min_recognized_text_length))
                    continue

                best_verse_info, highest_similarity, need_to_repeat = match_verse(recognized_text, rows)
                
                if highest_similarity < similarity_threshold:
                    print("Similarity below threshold, retry...")
                    continue

                if need_to_repeat == True:
                    print("Found similar verses, retry...")
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
     remaining_verses = [(verse[0], verse[1], verse[2]) for verse in rows if verse[0] == best_chapter and verse[1] >= best_verse]
    else:
        remaining_verses = []


    # POST MATCHING
    max_attempts_mismatch = 2  # Maximum number of consecutive mismatched attempts
    attempts_mismatch=0
    match_threshold = 0.38 
    print()

    while recognized_verse_number < remaining_verses[-1][1]:
        attempts_mismatch=0
        print()
        update_teleprompter(root, text_area, recognized_verse_number, remaining_verses, attempts_mismatch)

        root.update()  # Update the Tkinter window to show the verse

        while attempts_mismatch<max_attempts_mismatch:
            update_teleprompter(root, text_area, recognized_verse_number, remaining_verses, attempts_mismatch)
            recognized_text = run_transcription(transcription_recognizer, transcription_source, remaining_verses, recognized_verse_number+1)

            if recognized_text.startswith("بسم الله الرحمن الرحيم"):
                print("Recognized بسم الله الرحمن الرحيم. Continue...")
                continue
            
            elif re.search(r"(الله اكبر)", recognized_text):
                root.destroy()
                iteration_ct+=1
                print("Detected {}. Prayer action...".format(recognized_text))
                main()

            elif "UV ERROR" in recognized_text or "TIME ERROR" in recognized_text:
                print("Audio recognition error")
                print()
                continue

            best_verse_info, highest_similarity, need_to_repeat = match_verse(recognized_text, remaining_verses)
            versenum_realized=best_verse_info[-1]
            
            if versenum_realized:
                if len(best_verse_info)==2:
                    if(versenum_realized!=recognized_verse_number+1):
                        attempts_mismatch+=1
                        print("Incorrect match, retry...")
                        continue
                elif len(best_verse_info)==3:
                    if(versenum_realized!=recognized_verse_number):
                        attempts_mismatch+=1
                        print("Incorrect match, retry...")
                        continue

            if highest_similarity < match_threshold:
                attempts_mismatch+=1
                print("Similarity below threshold, retry...")
                continue
            
            break

        recognized_verse_number += 1  # Move to the next verse
        

    root.destroy()  # Close the teleprompter window

    root.mainloop()
    print()
    print("All remaining verses have been processed.")
    iteration_ct+=1

    print("iteration_ct", iteration_ct)
    if iteration_ct <= 12: # 12 different prayer actions
        main()

if __name__ == "__main__":
    main()