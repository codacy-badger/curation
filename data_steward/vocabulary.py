"""
Utility for creating OMOP vocabulary DRC resources. OMOP vocabulary files are downloaded from
[Athena](http://athena.ohdsi.org/) in tab-separated format. Before they can be loaded into BigQuery, they must
be reformatted and records for the AOU Generalization and AOU Custom vocabularies must be added to them.
"""
import csv
import logging
import os
import sys
import warnings
import re

from common import (CONCEPT, VOCABULARY, DELIMITER, LINE_TERMINATOR,
                    TRANSFORM_FILES, APPEND_VOCABULARY, APPEND_CONCEPTS,
                    ADD_AOU_VOCABS, ERRORS, ERROR_APPENDING, VOCABULARY_UPDATES,
                    AOU_GEN_ID, AOU_CUSTOM_ID)
from resources import AOU_VOCAB_PATH, AOU_VOCAB_CONCEPT_CSV_PATH, hash_dir
from io import open

RAW_DATE_PATTERN = re.compile(r'\d{8}$')
BQ_DATE_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2}$')

csv.field_size_limit(sys.maxsize)


def format_date_str(date_str):
    """
    Format a date string to yyyymmdd if it is not already
    :param date_str: the date string
    :return: the formatted date string
    :raises:  ValueError if a valid date object cannot be parsed from the string
    """
    if BQ_DATE_PATTERN.match(date_str):
        formatted_date_str = date_str
    elif RAW_DATE_PATTERN.match(date_str):
        parts = date_str[0:4], date_str[4:6], date_str[6:8]
        formatted_date_str = '-'.join(parts)
    else:
        raise ValueError('Cannot parse value {v} as date'.format(v=date_str))
    return formatted_date_str


def _transform_csv(in_fp, out_fp, err_fp=None):
    if not err_fp:
        err_fp = sys.stderr
    csv_reader = csv.reader(in_fp, delimiter=DELIMITER)
    header = next(csv_reader)
    date_indexes = []
    for index, item in enumerate(header):
        if item.endswith('_date'):
            date_indexes.append(index)
    csv_writer = csv.writer(out_fp,
                            delimiter=DELIMITER,
                            lineterminator=LINE_TERMINATOR)
    csv_writer.writerow(header)
    for row in csv_reader:
        try:
            for i in date_indexes:
                row[i] = format_date_str(row[i])
            csv_writer.writerow(row)
        except (ValueError, IndexError) as e:
            message = 'Error %s transforming row:\n%s' % (str(e), row)
            err_fp.write(message)


def transform_file(file_path, out_dir):
    """
    Format file date fields and standardize line endings a local csv file and save result in specified directory

    :param file_path: Path to the csv file
    :param out_dir: Directory to save the transformed file
    """
    file_name = os.path.basename(file_path)
    out_file_name = os.path.join(out_dir, file_name)
    err_dir = os.path.join(out_dir, ERRORS)
    err_file_name = os.path.join(err_dir, file_name)

    try:
        os.makedirs(err_dir)
    except OSError:
        logging.info(f"Error directory:\t{err_dir}\t already exists")

    with open(file_path,
              'r') as in_fp, open(out_file_name,
                                  'w') as out_fp, open(err_file_name,
                                                       'w') as err_fp:
        _transform_csv(in_fp, out_fp, err_fp)


def transform_files(in_dir, out_dir):
    """
    Transform vocabulary files in a directory and save result in another directory

    :param in_dir: Directory containing vocabulary csv files
    :param out_dir: Directory to save the transformed file
    """
    fs = os.listdir(in_dir)
    for f in fs:
        in_path = os.path.join(in_dir, f)
        transform_file(in_path, out_dir)


def get_aou_vocab_version():
    """
    Generate an identifier used to version AOU vocabulary resources

    :return: unique identifier string
    """
    return hash_dir(AOU_VOCAB_PATH)


def get_aou_vocabulary_row(vocab_id):
    """
    Get row for the vocabulary

    :param vocab_id:  vocabulary id to generate row for
    :return: a delimited string representing row of the vocabulary.csv file
    """
    aou_vocab_version = get_aou_vocab_version()
    # vocabulary_id vocabulary_name vocabulary_reference vocabulary_version vocabulary_concept_id
    vocab_row = VOCABULARY_UPDATES.get(vocab_id)
    vocab_row[-2] = aou_vocab_version
    return DELIMITER.join(vocab_row)


def _vocab_id_match(s):
    """
    Get a matching AOU vocabulary ID in the specified string, if any

    :param s: string to search for AOU vocabulary IDs
    :return: the first vocabulary ID found in the string, otherwise None
    """
    vocab_id_in_row_iter = (
        vocab_id for vocab_id in VOCABULARY_UPDATES if vocab_id in s)
    # if there are matches return the first one, otherwise None
    return next(vocab_id_in_row_iter, None)


def append_concepts(in_path, out_path):
    """
    Add AOU-specific concepts to the concept file at the specified path

    :param in_path: existing concept file
    :param out_path: location to save the updated concept file
    """
    with open(out_path, 'w') as out_fp:
        # copy original rows line by line for memory efficiency
        with open(in_path, 'r') as in_fp:
            for row in in_fp:
                # check if the vocab_id is in the row text
                vocab_id_in_row = _vocab_id_match(row)
                if vocab_id_in_row:
                    # skip it so it is appended below
                    warnings.warn(
                        ERROR_APPENDING.format(in_path=in_path,
                                               vocab_id=vocab_id_in_row))
                else:
                    out_fp.write(row)

        # append new rows
        with open(AOU_VOCAB_CONCEPT_CSV_PATH, 'r') as aou_gen_fp:
            # Sending the first five lines of the file because tab delimiters
            # are causing trouble with the Sniffer and has_header method
            five_lines = ''
            for _ in range(0, 5):
                five_lines += aou_gen_fp.readline()

            has_header = csv.Sniffer().has_header(five_lines)
            aou_gen_fp.seek(0)
            # skip header if present
            if has_header:
                next(aou_gen_fp)
            for row in aou_gen_fp:
                out_fp.write(row)


def append_vocabulary(in_path, out_path):
    """
    Add AOU-specific vocabularies to the vocabulary file at the specified path

    :param in_path: existing vocabulary file
    :param out_path: location to save the updated vocabulary file
    :return:
    """
    aou_general_row = get_aou_vocabulary_row(AOU_GEN_ID)
    aou_custom_row = get_aou_vocabulary_row(AOU_CUSTOM_ID)
    with open(out_path, 'w') as out_fp:
        # copy original rows line by line for memory efficiency
        with open(in_path, 'r') as in_fp:
            for row in in_fp:
                vocab_id_in_row = _vocab_id_match(row)
                if vocab_id_in_row:
                    # skip it so it is appended below
                    warnings.warn(
                        ERROR_APPENDING.format(in_path=in_path,
                                               vocab_id=vocab_id_in_row))
                else:
                    out_fp.write(row)
        # append AoU_General and AoU_Custom
        # newline needed here because write[lines] does not include line separator
        out_fp.write(aou_general_row + '\n')
        out_fp.write(aou_custom_row)


def add_aou_vocabs(in_dir, out_dir):
    """
    Add vocabularies AoU_General and AoU_Custom to the vocabulary at specified path

    :param in_dir: existing vocabulary files
    :param out_dir: location to save the updated vocabulary files
    :return:
    """
    file_names = os.listdir(in_dir)
    concept_in_path = None
    vocabulary_in_path = None
    # Case-insensitive search for concept and vocabulary files
    for file_name in file_names:
        table_name, _ = os.path.splitext(file_name.lower())
        in_path = os.path.join(in_dir, file_name)
        if table_name == CONCEPT:
            concept_in_path = in_path
        elif table_name == VOCABULARY:
            vocabulary_in_path = in_path
    if concept_in_path is None:
        raise IOError('CONCEPT.csv was not found in %s' % in_dir)
    if vocabulary_in_path is None:
        raise IOError('VOCABULARY.csv was not found in %s' % in_dir)

    concept_out_path = os.path.join(out_dir, os.path.basename(concept_in_path))
    append_concepts(concept_in_path, concept_out_path)

    vocabulary_out_path = os.path.join(out_dir,
                                       os.path.basename(vocabulary_in_path))
    append_vocabulary(vocabulary_in_path, vocabulary_out_path)


if __name__ == '__main__':
    import argparse

    arg_parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter)
    arg_parser.add_argument('command',
                            choices=[
                                TRANSFORM_FILES, ADD_AOU_VOCABS,
                                APPEND_VOCABULARY, APPEND_CONCEPTS
                            ])
    arg_parser.add_argument('--in_dir', required=True)
    arg_parser.add_argument('--out_dir', required=True)
    args = arg_parser.parse_args()
    if args.command == TRANSFORM_FILES:
        transform_files(args.in_dir, args.out_dir)
    elif args.command == ADD_AOU_VOCABS:
        add_aou_vocabs(args.in_dir, args.out_dir)
    elif args.command == APPEND_VOCABULARY:
        append_vocabulary(args.file, args.out_dir)
    elif args.command == APPEND_CONCEPTS:
        append_concepts(args.file, args.out_dir)
