from __future__ import print_function
from dicom_anon import dicom_anon
import dateparser
import argparse
import os
import csv
import uuid

# Global variables. Can be modified.
delimiter = " "
skip_first_line = True

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
parser.add_argument("-t", action="store_true",
                    help="test mode, ignores all other arguments if set")

# Retrieve input parameters.
args = parser.parse_args()
test_mode = args.t

if test_mode is True:
    # Test mode. Uses tests folder.
    skip_first_line = False
    kreftregisteret_csv = "tests/variables.csv"
    destination_variables_csv = "tests/cleaned_variables.csv"
    source_dicom_dir = "tests/identify"
    destination_dicom_dir = "tests/cleaned"
    parsed_modalities = ["mg"]

else:
    # Create a list from the comma separated modalities, so that they can be
    #  used in the dicom anon call to anonymize the DICOM files.
    kreftregisteret_csv = str(args.kreftregisteret_csv)
    destination_variables_csv = str(args.destination_variables_csv)
    source_dicom_dir = str(args.source_dicom_dir)
    destination_dicom_dir = str(args.destination_dicom_dir)
    parsed_modalities = str(args.modalities).split(",")


class NotImplementedError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)


def find_dicom_path(source_dir, person_id, invitation_id):
    if test_mode is True:
        return os.path.join(source_dir, person_id, invitation_id)
    # This function has three parameters: source_dir, person_id
    #  and invitation_id.
    # The return value is the absolute path to the DICOM files that
    #  corresponds to the given person ID and invitation ID.
    #
    # For example, if the directory structure is as follows:
    #
    # 1001/
    #     100001/
    #         file1.dicom
    #         file2.dicom
    #         file3.dicom
    # 1002/
    #     100020/
    #         otherfile1.dicom
    #         otherfile2.dicom
    #
    # , and 1001 and 1002 are person IDs, and 100001 and 100020 are
    #   invitation IDs, then the return value of this function should be:
    #   os.path.join(source_dir, person_id, invitation_id)
    #     => e.g. <source_dir>/1001/100001/
    raise NotImplementedError('needs to be implemented')


def deidentify_variables(variable_list):
    # This function accepts a list with variables from the csv file
    #  from Krefregisteret. The list of variables follows the same order
    #  as the variables from the csv file, but does not contain pID nor
    #  invID. The first element in the list is thus O2_Bildetakingsdato.
    #
    # This function does the following:
    #  - O2_Bildetakingsdato is converted from dd.mmm.yyyy to mmm.yyyy.
    #  - Diagnosedato is made relative from O2_Bildetakingsdato in days.
    screening_date = dateparser.parse(variable_list[0])
    diagnose_date = dateparser.parse(variable_list[7])

    variable_list[0] = "{0}-{1}".format(screening_date.month,
                                        screening_date.year)

    diagnose_screening_delta = diagnose_date - screening_date
    variable_list[7] = str(diagnose_screening_delta.days)

    return variable_list


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
                              profile="basic")
    da.run(source, destination)

    # Also anonymize file names of DICOM files.
    for idx, file in enumerate(os.listdir(destination)):
        # Get absolute file path to DICOM file.
        file_path = os.path.join(destination, file)

        # Rename DICOM to <idx>.dcm (starting idx from 1).
        new_file_path = os.path.join(destination, "{}.dcm".format(idx+1))
        os.rename(file_path, new_file_path)


# Open the metadata csv file from Kreftregisteret.
with open(kreftregisteret_csv, 'rb') as kr_csv:
    # Skip first line if it containers headers. This variable can be
    #  modified.
    if skip_first_line is True:
        next(kr_csv, None)

    # NB: It is assumed that the variables are separated by whitespaces.
    #  The delimiter can be changed by modifying the delimiter variable.

    # Initialize the csv reader.
    reader = csv.reader(kr_csv, delimiter=delimiter)

    # Initialize a dictionary for mapping pID and invID.
    # It is assumed that one pID can be associated with many invIDs.
    person_invitations_dict = {}

    # Load lines from the file. It is assumed that one line contains all
    #  variables for a single screening. A line should look like:
    #  2839 95643 15.012.2014 22 N 2 4 4 4 ...
    #  where the first two values in the line should be PID and InvID
    #  respectively.
    for line in reader:
        # The first two elements in an entry are assumed to be PID and InvID.
        # The third element is assumed to be O2_Bildetakingsdato.
        pID, invID = line[0:2]

        # De-identify the rest of the variables.
        variables = deidentify_variables(line[2:])

        # Check if pID already exists in the dictionary.
        # If it does, add new invID to the dictionary along with the other
        #  variables.
        # If it does not, create a new dictionary key with pID and store
        #  the first invID along with the other variables.
        if pID in person_invitations_dict:
            person_invitations_dict[pID][invID] = variables
        else:
            person_invitations_dict[pID] = {invID: variables}



# Now we have created a dictionary with pID and invID and the other
#  variables from the csv file.
# We use this dictionary to de-identify the original folder structure,
#  DICOM files and the csv file from Kreftregisteret.

print("Start anonymizing DICOMs of {} patients."
      .format(len(person_invitations_dict.keys())))

with open(destination_variables_csv, 'wb') as destination_csv:
    variable_writer = csv.writer(destination_csv, delimiter=delimiter)

    for pID, invIDs in person_invitations_dict.iteritems():
        # Create a random UUID.
        random_uuid = uuid.uuid4().hex

        # Define the path for the anonymized DICOM files.
        anonymized_patient_path = os.path.join(destination_dicom_dir,
                                               random_uuid)

        # Create the new directory ./<destination_dicom_dir>/<uuid>.
        os.makedirs(anonymized_patient_path)

        for invID, deidentified_variables in invIDs.iteritems():
            # Find path to DICOM files from pID and invID.
            original_screening_path = find_dicom_path(source_dicom_dir,
                                                      pID, invID)

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

print("Anonymization has finished.")

if test_mode is True:
    print("=== Test has run smoothly!") 
