#!/usr/bin/env python
'''
Broadly speaking, this script takes the audio downloaded from Common Voice
for a certain language, in addition to the *.tsv files output by CorporaCreator,
and the script formats the data and transcripts to be in a state usable by
DeepSpeech.py
Use "python3 import_cv2.py -h" for help
'''
from __future__ import absolute_import, division, print_function

# Make sure we can import stuff from util/
# This script needs to be run from the root of the DeepSpeech repository
import os
import sys
sys.path.insert(1, os.path.join(sys.path[0], '..'))

import csv
import sox
import argparse
import subprocess
import progressbar
import unicodedata
import shutil
import glob
import re
import pandas as pd
import numpy as np
import hgtk

from sklearn.model_selection import train_test_split
from os import path
from threading import RLock
from multiprocessing.dummy import Pool
from multiprocessing import cpu_count
from util.downloader import SIMPLE_BAR
from util.text import Alphabet, validate_label, UTF8Alphabet
from util.feeding import secs_to_hours
from util.regex import addspace

FIELDNAMES = ['wav_filename', 'wav_filesize', 'transcript']
SAMPLE_RATE = 16000
MAX_SECS = 15
DATASET = ['train', 'test', 'dev']

def _preprocess_data(data_dir, audio_dir, label_filter, space_after_every_character=False):
    
    data_dir_list = [ path.join(path.abspath(data_dir),a)  for a in os.listdir(data_dir) if os.path.isdir(path.join(path.abspath(data_dir),a)) ]
    #print(data_dir_list)
    trans_list = []
    rows = []
    lock = RLock()
    wrong_rows = []
    short_rows = []
    long_rows = []
    org_rows = []

    for dir in data_dir_list :
        flacfiles = [ a for a in os.listdir(dir) if a.endswith(".flac")]
        #print(dir)
        for file in flacfiles :
            abs_flacfile = path.join(path.abspath(dir), file)
            wavfile = re.sub('.flac', '.wav', file)
            abs_wavfile = path.join(path.abspath(audio_dir),wavfile)
            _maybe_convert_wav(abs_flacfile, abs_wavfile)


        transcript = [ path.join(path.abspath(dir), a) for a in os.listdir(dir) if a.endswith(".txt")]
        trans_list.append(transcript)

    for trans in trans_list :
        print(trans[0])
        with open(trans[0], 'r', encoding='utf-8') as f:
            line = f.readline()
            while line :
                #wav_file = path.join(audio_dir, line[0:12] + ".wav")
                wav_file = path.join( path.abspath(audio_dir), line[0:12] + ".wav")
                #print(wav_file)
                file_size = -1
                file_size = path.getsize(wav_file)
                #print(file_size)
                frames = int(subprocess.check_output(['soxi', '-s', wav_file], stderr=subprocess.STDOUT))

                org_line = line = line[13:].lower()
                line = addspace(line)
                line = hgtk.text.decompose(line)
                
                org_rows.append((wav_file, file_size, org_line))

                line = re.sub('[ᴥ]', ' ', line)
                line = re.sub('[\n]', ' ', line)
                #print(line)
                #line = line.lower()
                label = label_filter(line)
                
                #print(label)
                if label == None:
                    print("line is NULL")

                #print (wav_file, file_size, label)
                with lock:
                    if file_size == -1:
                        # Excluding samples that failed upon conversion
                        pass
                    elif label is None:
                        wrong_rows.append((wav_file, file_size, label))
                        pass
                        # Excluding samples that failed on label validation
                    elif int(frames/SAMPLE_RATE*1000/10/2) < len(str(label)):
                        short_rows.append((wav_file, file_size, label))
                        pass
                        # Excluding samples that are too short to fit the transcript
                    elif frames/SAMPLE_RATE > MAX_SECS:
                        long_rows.append((wav_file, file_size, label))
                        pass
                        # Excluding very long samples to keep a reasonable batch-size
                    else:
                        # This one is good - keep it for the target CSV
                        rows.append((wav_file, file_size, label))

                line = f.readline()

    total_csv = path.join(audio_dir,"total.csv")
    with open (total_csv, 'w', encoding='utf-8') as total :
        writer = csv.DictWriter(total, fieldnames=FIELDNAMES)
        writer.writeheader()
        for filename, file_size, transcript in rows :
            writer.writerow({'wav_filename': filename, 'wav_filesize':file_size , 'transcript':transcript})

    org_total_csv = path.join(audio_dir,"org_total.csv")
    with open (org_total_csv, 'w', encoding='utf-8') as total :
        writer = csv.DictWriter(total, fieldnames=FIELDNAMES)
        writer.writeheader()
        for filename, file_size, transcript in org_rows :
            writer.writerow({'wav_filename': filename, 'wav_filesize':file_size , 'transcript':transcript})

    with open (total_csv, 'r', encoding='utf-8') as total :
        df = pd.read_csv(total)

        train, test = train_test_split(df, test_size = 1/40, random_state=123)
        train, dev = train_test_split(train, test_size = 1/10, random_state=123)
        #print(test)
        train_csv = path.join(path.abspath(audio_dir), "train.csv")
        train.to_csv(train_csv, mode='w', index = False)
        dev_csv = path.join(path.abspath(audio_dir), "dev.csv")
        dev.to_csv(dev_csv, mode='w', index = False)
        test_csv = path.join(path.abspath(audio_dir), "test.csv")
        test.to_csv(test_csv, mode='w', index = False)
        
        trans_csv = path.join(path.abspath(audio_dir), "trans.csv")
        trans = df.loc[:, 'transcript']
        trans.to_csv(trans_csv, 'w', index = False)

    wrong_csv = path.join(audio_dir,"wrong.csv")
    with open (wrong_csv, 'w', encoding='utf-8') as wrong :
        writer = csv.DictWriter(wrong, fieldnames=FIELDNAMES)
        writer.writeheader()
        for filename, file_size, transcript in wrong_rows :
            writer.writerow({'wav_filename': filename, 'wav_filesize':file_size , 'transcript':transcript})

    short_csv = path.join(audio_dir,"short.csv")
    with open (short_csv, 'w', encoding='utf-8') as short :
        writer = csv.DictWriter(short, fieldnames=FIELDNAMES)
        writer.writeheader()
        for filename, file_size, transcript in short_rows :
            writer.writerow({'wav_filename': filename, 'wav_filesize':file_size , 'transcript':transcript})

            
    long_csv = path.join(audio_dir,"long.csv")
    with open (long_csv, 'w', encoding='utf-8') as long :
        writer = csv.DictWriter(long, fieldnames=FIELDNAMES)
        writer.writeheader()
        for filename, file_size, transcript in long_rows :
            writer.writerow({'wav_filename': filename, 'wav_filesize':file_size , 'transcript':transcript})


def _maybe_convert_wav(mp3_filename, wav_filename):
    if not path.exists(wav_filename):
        transformer = sox.Transformer()
        transformer.convert(samplerate=SAMPLE_RATE)
        try:
            transformer.build(mp3_filename, wav_filename)
        except sox.core.SoxError:
            pass


if __name__ == "__main__":
    PARSER = argparse.ArgumentParser(description='Import CommonVoice v2.0 corpora')
    PARSER.add_argument('data_dir', help='Directory containing raw data files')
    PARSER.add_argument('--audio_dir', help='Directory containing the audio clips - defaults to "<data_dir>/clips"')
    PARSER.add_argument('--filter_alphabet', help='Exclude samples with characters not in provided alphabet')
    PARSER.add_argument('--normalize', action='store_true', help='Converts diacritic characters to their base ones')
    PARSER.add_argument('--space_after_every_character', action='store_true', help='To help transcript join by white space')

    PARAMS = PARSER.parse_args()

    AUDIO_DIR = PARAMS.audio_dir if PARAMS.audio_dir else os.path.join(PARAMS.data_dir, 'clips')
    ALPHABET = Alphabet(PARAMS.filter_alphabet) if PARAMS.filter_alphabet else None

    def label_filter_fun(label):
        if PARAMS.normalize:
            label = unicodedata.normalize("NFKD", label.strip()) \
                .encode("ascii", "ignore") \
                .decode("ascii", "ignore")
        label = validate_label(label)
        if ALPHABET and label:
            try:
                ALPHABET.encode(label)
            except KeyError:
                label = None
        return label

    _preprocess_data(PARAMS.data_dir, AUDIO_DIR, label_filter_fun, PARAMS.space_after_every_character)