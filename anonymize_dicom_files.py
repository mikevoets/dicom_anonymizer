from dicom_anon import dicom_anon
import dateparser
import argparse
import os
import csv
import uuid

# Requirements (see requirements.txt):
#  Python 2.7
#  Pydicom
#  Sqlite3

# Global variables. Can be modified.
delimiter = " "
skip_first_line = False


# Input parameters:
#  metadata Path to csv file from Kreftregisteret.
#  source Source directory.
#      The root directory with the original DICOM files.
#  target Target directory.
#      The root directory where the anonymized DICOM files should be
#      transferred to.
#  --modalities -m (optional) Restrict modalities.
#      By default only MG and OT will be allowed.

parser = argparse.ArgumentParser(description="Anonymize DICOM files.")
parser.add_argument("metadata_path", type=str,
                    help="path to csv file containing metadata")
parser.add_argument("source_dir", type=str,
                    help="root path to source directory with DICOM files")
parser.add_argument("target_dir", type=str,
                    help="root path to target directory where anonymized "
                         "DICOM files should be copied to")
parser.add_argument("-m", "--modalities", type=str, default="ot,mg",
                    help="restrict modalities, comma separated "
                         "(default: ot,mg)")

# Retrieve input parameters.
args = parser.parse_args()

# Create a list from the comma separated modalities, so that they can be
#  used in the dicom anon call to anonymize the DICOM files.
parsed_modalities = str(args.modalities).split(",")
source = str(args.source_dir)
metadata_path = str(args.metadata_path)


def find_dicom_path(person_id, invitation_id):
    # This function has two parameters: person_id and invitation_id.
    # The return value is the path to the DICOM files relative from the
    #  input parameter `source_dir`, that corresponds to the given
    #  person ID and invitation ID.
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
    #   os.path.join(person_id, invitation_id)  # => e.g. 1001/100001/
    pass


def deidentify_variables(variable_list):
    # This function accepts a list with variables from the csv file
    #  from Krefregisteret. The list of variables follows the same order
    #  as the variables from the csv file, but does not contain pID nor
    #  invID. The first element in the list is thus O2_Bildetakingsdato.
    #
    # This function does the following:
    #  - O2_Bildetakingsdato is converted from dd.mmm.yyyy to yyyy.
    #  - Diagnosedato is made relative from O2_Bildetakingsdato in days.
    screening_date = dateparser.parse(variable_list[0])
    diagnose_date = dateparser.parse(variable_list[7])

    variable_list[0] = str(screening_date.year)

    diagnose_screening_delta = diagnose_date - screening_date
    variable_list[7] = str(diagnose_screening_delta.days)

    return variable_list


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
da = dicom_anon.DicomAnon(quarantine="quarantine", audit_file="identity.db",
                          modalities=parsed_modalities, profile="basic")


# Open the metadata csv file from Kreftregisteret.
with open(metadata_path, 'rb') as metadata:
    # Skip first line if it containers headers. This variable can be
    #  modified.
    if skip_first_line is True:
        next(metadata, None)

    # NB: It is assumed that the variables are separated by whitespaces.
    #  The delimiter can be changed by modifying the delimiter variable.

    # Initialize the csv reader.
    reader = csv.reader(metadata, delimiter=delimiter)

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
        variables = deidentify_variables(line[3:])

        # Check if pID already exists in the dictionary.
        # If it does, add new invID to the dictionary along with the other
        #  variables.
        # If it does not, create a new dictionary key with pID and store
        #  the first invID along with the other variables.
        if pID in person_invitations_dict:
            person_invitations_dict[pID][invID] = variables
        else:
            person_invitations_dict[pID] = {invID: variables}



# Now we have achieved a dictionary with pID and invID and the other
#  variables from the csv file.

for pID, invIDs in person_invitations_dict:
    # Create a random UUID.
    uuid = uuid.uuid4().hex

    # Define the path for the anonymized DICOM files.
    anonymized_patient_path = os.path.join(target_dir, uuid)

    # Create the new directory ./<target_dir>/<uuid>.
    os.makedirs(anonymized_patient_path)

    for invID, variables in invIDs:
        # Find path to DICOM files from pID and invID.
        # TODO: Needs to be implemented. See line 16.
        original_screening_path = find_dicom_path(pID, invID)

        # Retrieve the screening date from the list of variables.
        screening_date = variables[0]

        # Define a new directory inside the anonymized patient directory.
        #  We use the screening date as the directory name.
        anonymized_screening_path = os.path.join(anonymized_patient_path,
                                                 screening_date)

        # Anonymize the DICOM files from `dicom_path`,
        #  and place the anonymized DICOM files into
        #  the `anonymized_screening_path`.
        da.run(original_screening_path, anonymized_screening_path)

        # TODO: Write variables to a new de-identified csv file.
