Written by Mike Voets, UiT Arctic University of Norway, 2018.

# Python DICOM Anonymizer

This is a Python script for anonymization of DICOM files, and can be used from the command line. It takes a source csv file with variables and a source directory containing DICOM files, anonymizes them, and places them to the specified destination. The source csv file will also be de-identified and written to the specific destination. The anonymized DICOM files are also renamed in order to not remain having any sensitive information.

### Notice

The source csv file should contain variables from Kreftregisteret in a specific order. It is assumed that the personal ID, invitation ID, screening date, and diagnosis date, are the 1st, 2nd, 3rd, and 10th variable in each row in the csv file, respectively.

__!!!__: The function `.find_dicom_path` in `anonymize_dicom_files.py` on line 65 must be implemented in order to be able to run this script successfully.

## Prerequisites

The script runs with Python 2.7. See the [requirements](requirements.txt) for what third-party requirements you will need to have installed.

You can install all requirements by using pip:

```
pip install -U -r requirements.txt
```

You will also need to load the dicom-anon submodule (assuming you have Git):

```
git submodule update --init
```

## Example

Assume the identified DICOM files are in a directory called `identified` in your home directory, and you want the de-identified files to be placed in a directory called `cleaned` in your home directory.

The variables from Kreftregisteret are placed in a csv file called `variables.csv`, and you want the de-identified variables to be placed in a new csv file called `cleaned_variables.csv`.

The following example starts the script, and uses [dicom-anon](https://github.com/chop-dbhi/dicom-anon) to de-identify the DICON files. Dicom-anon attempts to be compliant with the Basic Application Level Confidentiality Profile as specified in [DICOM 3.15 Annex E document](ftp://medical.nema.org/medical/dicom/2011/11_15pu.pdf) on page 85.

The de-identifier script creates a sqlite database with a table containing the original and cleaned version of every attribute. This file can be removed after running this script. Files that are explicitly marked as containing burnt-in data along with files that have a series description of "Patient Protocol", will be copied to the `quarantine` folder.

```
python anonymize_dicom_files.py variables.csv cleaned_variables.csv identified cleaned
```

As a default only [modalities](https://www.dicomlibrary.com/dicom/modality/) MG and OT are allowed. If for any reason you need to specify other modalities, you will need to use the `--modalities` argument and specify the allowed modalities yourself. Multiple modalities should be comma-separated.


## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.
