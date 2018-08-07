from __future__ import print_function
from dicom_anon import dicom_anon
import dicom
import dateparser
import argparse
import os
import csv
import uuid
import fnmatch
import logging
import re


# Set working directory to directory of this file.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Global variables. Can be modified.
delimiter = ";"
skip_first_line = True
dicom_extension = "dcm"
white_list_laterality = "white_list_laterality.json"
log_file = "anonymize_dicom_files.log"

# Input parameters:
#  kreftregisteret_csv Path to csv file from Kreftregisteret.
#  destination_variables_csv Path to csv file for de-identified variables.
#  source_dicom_dir Source directory.
#      The root directory with the original DICOM files.
#  destination_dicom_dir Target directory.
#      The root directory where the anonymized DICOM files should be
#      transferred to.
#  --modalities -m (optional) Restrict modalities.
#      By default only MG and OT will be allowed.
#  -t For testing purposes.
parser = argparse.ArgumentParser(description="Anonymize DICOM files.")
parser.add_argument("kreftregisteret_csv", type=str, nargs="?",
                    help="path to csv file containing variables from "
                         "Kreftregisteret")
parser.add_argument("kreftregisteret_links_csv", type=str, nargs="?",
                    help="path to csv file containing links to variables file")
parser.add_argument("destination_variables_csv", type=str, nargs="?",
                    help="path to csv file where de-identified variables "
                         "should be written to")
parser.add_argument("source_dicom_dir", type=str, nargs="?",
                    help="root path to source directory with DICOM files")
parser.add_argument("destination_dicom_dir", type=str, nargs="?",
                    help="root path to destination directory where anonymized "
                         "DICOM files should be written to")
parser.add_argument("-m", "--modalities", type=str, default="ot,mg",
                    help="restrict modalities, comma separated "
                         "(default: ot,mg)")
parser.add_argument("-d", "--debug_file", type=str, default=log_file,
                    help="load debug file to recreate index")
parser.add_argument("-t", action="store_true",
                    help="test mode, ignores all other arguments if set")

# Retrieve input parameters.
args = parser.parse_args()
test_mode = args.t

if test_mode is True:
    # Test mode. Uses tests folder.
    skip_first_line = False
    links_csv = "tests/links.csv"
    kreftregisteret_csv = "tests/variables.csv"
    destination_variables_csv = "tests/cleaned_variables.csv"
    source_dicom_dir = "tests/identify"
    destination_dicom_dir = "tests/cleaned"
    parsed_modalities = ["mg"]
else:
    # Create a list from the comma separated modalities, so that they can be
    #  used in the dicom anon call to anonymize the DICOM files.
    links_csv = str(args.kreftregisteret_links_csv)
    kreftregisteret_csv = str(args.kreftregisteret_csv)
    destination_variables_csv = str(args.destination_variables_csv)
    source_dicom_dir = str(args.source_dicom_dir)
    destination_dicom_dir = str(args.destination_dicom_dir)
    parsed_modalities = str(args.modalities).split(",")

debug_file = str(args.debug_file)
load_debug_file = False

if os.path.isfile(debug_file):
    answer = raw_input('Found loadable debug file ({}). ' \
                       'Want to load it to skip indexing? Y/n ' \
                       .format(debug_file))
    if answer == 'y' or answer == 'Y':
        load_debug_file = True

if load_debug_file:
    logging.basicConfig(filename=log_file, filemode='a', level=logging.DEBUG)
else:
    logging.basicConfig(filename=log_file, filemode='w', level=logging.DEBUG)


def find_dicom_paths(source_dir, extension=dicom_extension):
    # Returns a list of paths to all dicom files that exist in source_dir.
    matches = []
    for root, dirnames, filenames in os.walk(source_dir):
        for filename in fnmatch.filter(filenames, '*.{}'.format(extension)):
            matches.append(os.path.join(root, filename))
    return matches


def recreate_study_index_from_file(file):
    index = {}
    with open(file, "r") as f:
        next(f, None)
        for line in f:
            entry = line.replace('DEBUG:root:', '', 1).rstrip("\r\n").split(' => ')
            if len(entry) != 2:
                return index
            index[entry[0]] = {'directory': entry[1]}
    return index


def create_study_index(dicom_paths):
    def commonprefix(l):
        # os.path.commonprefix always returns path prefixes
        # as it compares path component wise.
        cp = []
        ls = [p.split(os.sep) for p in l]
        ml = min(len(p) for p in ls)

        for i in range(ml):

            s = set(p[i] for p in ls)
            if len(s) != 1:
                break

            cp.append(s.pop())

        return '/'.join(cp)


    # Creates a dictionary index of StudyIDs and paths to DICOM
    #  files with classification number.
    index = {}

    total = len(dicom_paths)
    for i, path in enumerate(dicom_paths):
        print('\rIndexing DICOM files. {0:>10}/{1}'.format(i+1, total), end='')
        f = dicom.read_file(path)
        dir = os.path.dirname(path)

        if f.StudyID in index:
            idx_dir = index[f.StudyID]['directory']
            # Can be subdirectory, so we traverse down to find common ancestor.
            if idx_dir != dir:
                common_ancestor_dir = commonprefix([dir, idx_dir])

                if common_ancestor_dir == source_dicom_dir:
                    common_slashes = min(
                        [len(idx_dir.split('/')), len(dir.split('/'))])
                    dir = '/'.join(dir.split('/')[0:common_slashes])
                    idx_dir = '/'.join(idx_dir.split('/')[0:common_slashes])
                    raise TypeError(
                        'Unexpected studyID in multiple directories:\n' \
                        'Same studyID in "{0}" and "{1}"!'.format(dir, idx_dir))

                dir = os.path.normpath(common_ancestor_dir)

        index[f.StudyID] = {'directory': dir}

    print('\x1b[2K\rIndexed all DICOM files.')
    logging.debug('Indexed following StudyIDs with paths:')
    for studyID, var in index.iteritems():
        logging.debug('{0} => {1}'.format(studyID, var['directory']))

    return index


def anonymize_dicoms(source, destination):
    # Create an instance of the dicom anonymizer (dicom-anon).
    #  quarantine: The folder where DICOMs that cannot be anonymized are copied
    #              to. This may happen due to various reasons:
    #               1) files that do not match the allowed modalities,
    #               2) files that are explicitly marked as containing burnt-in
    #                  data,
    #               3) files that have a series description of "Patient Protocol".
    #  audit_file: The anonymizer creates a sqlite database with a table
    #              containing the original and cleaned version of every attribute
    #              in the AUDIT dictionary defined at the top of the source file.
    #  modalities: Allowed to-be-parsed modalities.
    #  profile:    For de-identification, 'basic' profile attempts to be
    #              compliant with the Basic Application Level Confidentiality
    #              Profile as specified in DICOM 3.15 Annex E document, page 85:
    #              ftp://medical.nema.org/medical/dicom/2011/11_15pu.pdf.
    #  See https://github.com/chop-dbhi/dicom-anon for more information.
    da = dicom_anon.DicomAnon(quarantine="quarantine",
                              audit_file="identity.db",
                              modalities=parsed_modalities,
                              profile="clean",
                              white_list=os.path.abspath(white_list_laterality))
    da.run(source, destination)


def find_substr(collection, substr):
    r = re.compile(r"(\S*\b{}\b\S*)".format(substr))
    f = filter(r.match, collection)
    if len(f) == 1:
        return f[0]
    elif len(f) > 1:
        logging.warning("Two matches for {} => {}".format(substr, f))
        return f[0]


def create_links_index(csv_file):
    index = {}
    print('\rIndexing links file.')
    with open(csv_file, 'rb') as f:
        if skip_first_line is True:
            next(f, None)
        reader = csv.reader(f, delimiter=delimiter)
        for line in reader:
            pID, _, invID, invNR = line
            if pID in index:
                if invID in index[pID]:
                    logging.warning("InvID {} in links file twice!" \
                                    .format(invID))
                else:
                    index[pID][invID] = invNR
            else:
                index[pID] = {invID: invNR}
    print('Indexed links file.')
    return index


# Create an index for studies and invitations.
if load_debug_file:
    study_idx = recreate_study_index_from_file(debug_file)
else:
    paths = find_dicom_paths(source_dicom_dir)
    study_idx = create_study_index(paths)

person_invitations_idx = {}
links_idx = create_links_index(links_csv)

# The keys of the index are the invNRs (studyIDs/screenings from DICOM files).
study_idx_invNRs = study_idx.keys()

# Open the links csv file.
with open(kreftregisteret_csv, 'rb') as f:
    # Skip first line if it containers headers. This variable can be
    #  modified.
    if skip_first_line is True:
        next(f, None)

    # NB: It is assumed that the variables are separated by whitespaces.
    #  The delimiter can be changed by modifying the delimiter variable.
    reader = csv.reader(f, delimiter=delimiter)

    # Load lines from the file. It is assumed that one line contains all
    #  variables for a single screening. A line should look like:
    #  2839 95643 15.012.2014 22 N 2 4 4 4 ...
    #  where the first two values in the line should be PID and InvID
    #  respectively.
    counter = 1
    for line in reader:
        print('Linking variables with index. {0}'.format(counter), end='')
        counter += 1
        # The first two elements in an entry are assumed to be PID and InvID.
        # The third element is assumed to be O2_Bildetakingsdato.
        pID, invID, variables = line[0], line[1], line[2:]

        # Retrieve the invitation number from the links file.
        try:
            invNR = links_idx[pID][invID]
        except KeyError:
            msg = 'pID: {0}, invID: {1} not in links index!'.format(pID, invID)
            print(msg)
            logging.warning(msg)
            continue

        # Retrieve the corresponding invitation number (studyID from the index).
        invNR_in_study_idx = find_substr(study_idx_invNRs, invNR)

        # Place the variables in the index for this invitation number.
        try:
            study_idx[invNR_in_study_idx]['variables'] = variables
        except KeyError:
            msg = 'No invNR/studyID {0} in study index (pID: {1}, invID: {2})' \
                  .format(invNR, pID, invID)
            print(msg)
            logging.warning(msg)
            continue

        # Check if pID already exists in the dictionary.
        # If it does, add new index entry (screening).
        # If it does not, create a new dictionary key with pID and store
        #  the first index entry (screening) along the dictionary key.
        if pID in person_invitations_idx:
            person_invitations_idx[pID].append(study_idx[invNR_in_study_idx])
        else:
            person_invitations_idx[pID] = [study_idx[invNR_in_study_idx]]

    print('\x1b[2K\rLinked all variables.')


# Now we have created a dictionary with pID and the screening metadata.
# We use this dictionary to de-identify the original folder structure,
#  DICOM files and the csv file from Kreftregisteret.

with open(destination_variables_csv, 'wb') as destination_csv:
    variable_writer = csv.writer(destination_csv, delimiter=delimiter)

    total = len(person_invitations_idx.keys())
    for i, person in enumerate(person_invitations_idx.iteritems()):
        print('\rAnonymizing DICOMs. {0:>10}/{1}'.format(i+1, total), end='')
        pID, screenings = person
        # Create a random UUID.
        random_uuid = uuid.uuid4().hex

        # Define the path for the anonymized DICOM files.
        anonymized_patient_path = os.path.join(destination_dicom_dir,
                                               random_uuid)

        # Create the new directory ./<destination_dicom_dir>/<uuid>.
        os.makedirs(anonymized_patient_path)

        for screening in screenings:
            # Find paths to DICOM files for this screening.
            original_screening_path = screening['directory']

            if original_screening_path == source_dicom_dir:
                logging.warning('Cannot anonymize base folder {} for pID: {}' \
                                .format(original_screening_path, pID))
                continue

            deidentified_variables = screening['variables']

            # Retrieve the screening month and year from the list of
            #  de-identified variables.
            screening_month_year = deidentified_variables[0]

            # Define a new directory inside the anonymized patient directory.
            #  We use the screening date as the directory name.
            anonymized_screening_path = os.path.join(anonymized_patient_path,
                                                     screening_month_year)

            # Anonymize the DICOM files from `dicom_path`,
            #  and place the anonymized DICOM files into
            #  the `anonymized_screening_path`.
            anonymize_dicoms(original_screening_path,
                             anonymized_screening_path)

            # Write variables to a new de-identified csv file.
            variable_writer.writerow([random_uuid] + deidentified_variables)

print('\x1b[2K\rAnonymization has finished.')

if test_mode is True:
    print('=== Test has run smoothly!')
