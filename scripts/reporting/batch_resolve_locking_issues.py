#!/usr/bin/env python
##
##  See COPYING file distributed along with the ncanda-data-integration package
##  for the copyright and license terms
##

import argparse
import pandas as pd
from pathlib import Path
import sibispy
import sibispy.cli
from sibispy import sibislogger as slog
import sys
from typing import Sequence, List, Dict, Mapping, Union
import yaml

import github
import pdb
from collections import defaultdict
import numpy as np

import batch_script_utils as utils
from commands import ExecRedcapLockingData


def run_batch(label, issue_numbers, metadata, verbose):
    title_string = "redcap_import_record:Failed to import into REDCap"
    issue_class = utils.get_class_for_label(label)

    scraped_issues = utils.scrape_matching_issues(
        slog, metadata, verbose, title_string, label, issue_numbers, issue_class
    )

    if not utils.verify_scraped_issues(scraped_issues):
        print("Aborting...")
        return

    closed_issues = []
    commented_issues = []
    for scraped_issue in scraped_issues:
        if verbose:
            print("\n" * 20)
            print(scraped_issue.stringify())

        for command in scraped_issue.get_commands():
            unlock_command = ExecRedcapLockingData(
                verbose, command.study_id, command.form, lock=False
            )
            lock_command = ExecRedcapLockingData(
                verbose, command.study_id, command.form, lock=True
            )
            unlock_command.test()
            command.test()
            lock_command.test()
            if not lock_command.success:
                print(f"Errors relocking:\n{lock_command.stringify_result()}")

        scraped_issue.update()
        if scraped_issue.resolved:
            closed_issues.append(f"#{scraped_issue.number}")
        else:
            commented_issues.append(f"#{scraped_issue.number}")

    if verbose:
        print(f"\n\nClosed:\n{', '.join(closed_issues)}")
        print(f"Commented:\n{', '.join(commented_issues)}")


def main():
    """
    Scrapes subject id's from all "Failed to import into redcap"-labeled
    issues with the passed label. Unlocks the locked form, reruns the script, and
    relocks the form. Comments on issues with the results, and closes them if
    no error is generated when rerunning the script.
    """
    args = _parse_args()
    session = _initialize(args)

    session.api.update({"data_entry": None})
    redcap_api = None
    try:
        redcap_api = session.connect_server("data_entry")
    except Exception as e:
        print(e.message)

    metadata = redcap_api.export_metadata(format="df").reset_index()[
        ["form_name", "field_name"]
    ]

    # Add form_complete field for each form
    forms = list(metadata["form_name"].unique())
    complete_fields = pd.DataFrame(
        {
            "field_name": [f"{form}_complete" for form in forms],
            "form_name": forms,
        }
    )

    metadata = metadata.append(complete_fields)

    config = _get_config(session)

    for label in args.labels:
        run_batch(label, args.issue_numbers, metadata, args.verbose)


def _parse_args(input_args: Sequence[str] = None) -> argparse.Namespace:
    """
    Parse CLI arguments.
    """
    parser = argparse.ArgumentParser(
        prog="batch_resolve_locking_issues",
        description="""Scrapes subject id's from all "Failed to import into redcap"-labeled
    issues with the passed label. Unlocks the locked form, reruns the script, and
    relocks the form. Comments on issues with the results, and closes them if
    no error is generated when rerunning the script.""",
    )

    parser.add_argument(
        "--labels",
        help="Which labels to scrape issues for (options: redcap_update_summary_scores, update_visit_data, import_mr_sessions, update_summary_forms). Separated by spaces.",
        nargs="+",
        action="store",
        default=None,
    )
    parser.add_argument(
        "--issue_numbers",
        help="Which issue numbers to scrape issues for. Separated by spaces.",
        nargs="+",
        type=int,
        action="store",
        default=None,
    )

    sibispy.cli.add_standard_params(parser)
    return parser.parse_args(input_args)


def _initialize(args: argparse.Namespace) -> sibispy.Session:
    """
    Initialize sibispy.Session and start the logger
    """
    slog.init_log(
        verbose=args.verbose,
        post_to_github=True,
        github_issue_title="batch_resolve_locking_issues",
        github_issue_label="bug",
        timerDir=None,
    )

    session = sibispy.Session()
    if not session.configure():
        raise RuntimeError("sibispy is not configured; aborting!")
        sys.exit(1)

    return session


def _get_config(session):
    """
    Get the handle for sibis_sys_config.yml.
    """

    parser, error = session.get_config_sys_parser()  # from here, .get_category
    return parser


if __name__ == "__main__":
    main()
