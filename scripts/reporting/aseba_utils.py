##
##  See COPYING file distributed along with the ncanda-data-integration package
##  for the copyright and license terms
##
"""
A collection of utility functions used by aseba_prep.py and aseba_reformat.py
"""
from __future__ import print_function
from __future__ import division
from builtins import str
from builtins import range
from past.utils import old_div
import pandas as pd
import re

def process_demographics_file(filename):
    """
    Subset and rename columns in a demographics file from an NCANDA release.

    Return with standard release index set in the DataFrame.
    """
    df = pd.read_csv(filename)
    # df = df[df['visit'] == 'baseline']
    df = df[['subject', 'arm', 'visit', 'participant_id', 'visit_age', 'sex']]
    df['mri_xnat_sid'] = df['subject']
    df = df.rename(columns={'participant_id': 'study_id',
                            'visit_age': 'age'})
    df.set_index(['subject', 'arm', 'visit'], inplace=True)
    return df


def get_year_set(year_int):
    """
    Given an integer year, get Redcap event names up to and including the year.

    Redcap event names are formatted as in redcap_event_name returned by Redcap
    API (i.e. "X_visit_arm_1").

    Integer-based year: 0 = baseline, 1 = followup_1y, ...

    Only allows for full-year standard-arm events.
    """
    events = ["baseline"]
    events.extend([str(i) + "y" for i in range(1, 10)])
    events = [e + "_visit_arm_1" for e in events]
    return events[0:(year_int + 1)]


def load_redcap_summary(file, index=True):
    """
    Load a release file. Optionally, set its primary keys as pandas indices.
    """
    index_col = ['subject', 'arm', 'visit'] if index else None
    df = pd.read_csv(file, index_col=index_col, dtype=object, low_memory=False)
    return df


def load_redcap_summaries(files):
    """
    Given a list of release files, return their horizontal concatenation.
    """
    return pd.concat([load_redcap_summary(x) for x in files], axis=1)


def get_id_lookup_from_demographics_file(demographics_df):
    """
    Extract a lookup (Redcap ID -> NCANDA SID) from a demographics DataFrame.

    Expects a demographics_df outputted by `process_demographics_file`.
    """
    return (demographics_df
            .reset_index()
            .set_index('study_id')
            .to_dict()
            .get('mri_xnat_sid'))


def api_result_to_release_format(api_df, id_lookup_dict=None, verbose=False):
    """
    Reindex a PyCAP API result to an NCANDA release format.

    REDCap API, when used with PyCAP, returns results as a DataFrame indexed by
    NCANDA ID (study_id - X-00000-Y-0) and combined event + arm
    (redcap_event_name)

    On the other hand, release files are typically indexed by XNAT ID
    (NCANDA_S0?????; mri_xnat_id in Redcap).

    This function will:

    1. Convert Redcap IDs to NCANDA SIDs using id_lookup_dict (as generated by
        `get_id_lookup_from_demographics_file`) or the `mri_xnat_sid` column
        (if present in api_df),
    2. Drop Redcap IDs that cannot be converted in that way,
    3. Separate event and arm to individual columns and make their names
        release-compatible,
    4. Return DataFrame indexed by release primary keys (subject, arm, visit).
    """

    df = api_df.copy(deep=True)
    df.reset_index(inplace=True)
    if id_lookup_dict:
        df['subject'] = df['study_id'].map(id_lookup_dict)
    elif 'mri_xnat_sid' in df.columns:
        df['subject'] = df['mri_xnat_sid']
    else:
        raise IndexError("You must supply id_lookup_dict, or api_df has to "
                         "have the mri_xnat_sid column")
    nan_idx = df['subject'].isnull()
    if verbose:
        study_id_nans = df.loc[nan_idx, 'study_id'].tolist()
        print ("Dropping study IDs without corresponding NCANDA SID: " +
               ", ".join(study_id_nans))
    df = df[~nan_idx]
    df[['visit', 'arm']] = (df['redcap_event_name']
                            .str.extract(r'^(\w+)_(arm_\d+)$'))

    def clean_up_event_string(event):
        """
        If possible, convert Redcap event name to NCANDA release visit name.

        If conversion fails, return the original string.

        Intended to be passed to pd.Series.map.
        """
        # NOTE: Only accounts for full Arm 1 events
        match = re.search(r'^(baseline|\dy)', event)
        if not match:
            return event
        elif re.match('^\d', match.group(1)):
            return "followup_" + match.group(1)
        else:
            return match.group(1)

    df['visit'] = df['visit'].map(clean_up_event_string)

    def clean_up_arm_string(arm):
        """
        If possible, convert Redcap arm name to NCANDA release arm name.

        If conversion fails, return the original string.

        Intended to be passed to pd.Series.map.
        """
        arm_dict = {'arm_1': 'standard',
                    'arm_2': 'recovery',
                    'arm_3': 'sleep',
                    'arm_4': 'maltreated'}
        if arm not in arm_dict:
            return arm
        else:
            return arm_dict[arm]

    df['arm'] = df['arm'].map(clean_up_arm_string)

    return df.set_index(['subject', 'arm', 'visit'])


def cbc_colname_sorter(colname):
    """
    Extract a machine-sortable number from CBCL columns.

    Luckily, section doesn't matter - question numbers increase monotonically,
    so all that's necessary is to extract them. An extra wrinkle is question
    56, which has letter-numbered parts, so we'll make that a decimal and add
    it to the extracted number; this should result in correct sorting.

    Intended to be passed to sort as a key function.
    """
    match = re.search(r'(\d+)([a-h]?)$', colname)
    if not match:
        return None
    else:
        number = float(match.group(1))
        letter = match.group(2)
        if len(letter) > 0:
            letter = old_div((ord(letter) - 96), 100)
        else:
            letter = 0.0
    return number + letter
