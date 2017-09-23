import re
import os
import os.path
import sys
import time
import logging
import argparse
import datetime
import configparser


logger = logging.getLogger(__name__)


CONF_NAME = '.satmonrc'
CONF_SECTION_DEFAULT = 'all'
DAY_NAMES = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
             'saturday']
SUBJECT_SIBLINGS = 'siblings'
SUBJECT_NEPHEWS = 'nephews'

DEFAULTS = """
[all]
move=newphews
schedule=
"""


class SaturdayMorning(object):
    def __init__(self, src_dir, date=None, dry_run=False):
        if not os.path.isdir(src_dir):
            raise Exception("Source directory doesn't exist: %s" % src_dir)
        self.src_dir = src_dir
        self.dry_run = dry_run
        self.today = _parse_date(date)
        self._did_something = False

    def run(self, dst_dir):
        self._did_something = False
        self._runOn(self.src_dir, dst_dir)
        if not self._did_something:
            logger.info("Nothing to do.")

    def _runOn(self, src_dir, dst_dir):
        conf_path = os.path.join(src_dir, CONF_NAME)
        if os.path.isfile(conf_path):
            # Found a config file! See if we should move anything here.
            logging.debug("Found config in: %s" % src_dir)
            config = configparser.ConfigParser()
            config.read_string(DEFAULTS)
            with open(conf_path, 'r') as fp:
                config.readfp(fp)

            self._moveSubjects(src_dir, dst_dir, config)
        else:
            # Nope... let's recurse...
            logging.debug("Recursing into: %s" % src_dir)
            for entry in os.listdir(src_dir):
                entry_path = os.path.join(src_dir, entry)
                if os.path.isdir(entry_path):
                    cur_dst_dir = os.path.join(dst_dir, entry)
                    self._runOn(entry_path, cur_dst_dir)

    def _moveSubjects(self, src_dir, dst_dir, config):
        subjects = config.get(CONF_SECTION_DEFAULT, 'move')

        entries = _get_ordered_entries(src_dir)
        if not entries:
            logger.debug("Directory '%s' is empty... skipping." % src_dir)
            return

        config_opts = _tuples_to_dict(config.items(CONF_SECTION_DEFAULT))
        if subjects == SUBJECT_NEPHEWS:
            first_entry = None
            for entry in entries:
                logger.debug("Inspecting nephews in '%s'..." % entry)
                n_src_dir = os.path.join(src_dir, entry)
                n_dst_dir = os.path.join(dst_dir, entry)
                first_entry = _get_first_entry(n_src_dir)
                if first_entry:
                    src_dir = n_src_dir
                    dst_dir = n_dst_dir
                    if config.has_section(entry):
                        logger.debug(
                            "Using configuration overrides for: %s" % entry)
                        config_opts.update(
                            _tuples_to_dict(config.items(entry)))
                    break
                else:
                    logger.debug(
                            "Nephew directory '%s' is empty... skipping." %
                            n_src_dir)
            if not first_entry:
                logger.debug(
                        "No valid nephew found in '%s'... skipping." %
                        src_dir)
                return
        else:
            logger.debug("Using sibling '%s'." % entries[0])
            first_entry = entries[0]

        src_path = os.path.join(src_dir, first_entry)

        # Move items for this specific day.
        schedule = config_opts.get('schedule', None)
        if not schedule:
            raise Exception("No schedule specified for: %s" % src_path)

        logger.debug("Using schedule: %s" % schedule)
        weekday_num = int(time.strftime('%w', self.today))
        day_name = DAY_NAMES[weekday_num]

        do_move = False
        move_reason = None
        if schedule == 'daily':
            do_move = True
            move_reason = 'the schedule is daily.'
        if schedule == 'weekday':
            if weekday_num > 0 and weekday_num < 6:
                do_move = True
                move_reason = 'today is a weekday'
            else:
                move_reason = 'today is not a weekday'
        if schedule in DAY_NAMES:
            if DAY_NAMES.index(schedule) == weekday_num:
                do_move = True
                move_reason = 'today is a %s' % DAY_NAMES[weekday_num]
            else:
                move_reason = ("today is not a %s (it's a %s)" %
                               (schedule, DAY_NAMES[weekday_num]))
        if do_move:
            dst_path = os.path.join(dst_dir, first_entry)
            logger.info("Moving '%s' to '%s'..." % (src_path, dst_path))
            logger.info(" - Reason: %s" % move_reason)
            if not self.dry_run:
                os.renames(src_path, dst_path)
            else:
                logger.info("   (not really... this is a dry run)")
        elif move_reason:
            logger.debug("Not moving '%s': %s" % (src_path, move_reason))
        else:
            raise Exception("Unknown schedule: %s" % schedule)

        if do_move:
            self._did_something = True


def _parse_date(date):
    if not date:
        return time.localtime()
    date = _do_parse_date(date)
    logger.info("Running as if today was: %s" % time.strftime('%x', date))
    return date


def _do_parse_date(date):
    if date == 'yesterday':
        date = '-1'
    elif date == 'tomorrow':
        date = '+1'

    if date.startswith('+') or date.startswith('-'):
        today = datetime.datetime.now()
        today += datetime.timedelta(days=int(date))
        return today.timetuple()

    try:
        return time.strptime(date, "%Y/%m/%d")
    except:
        raise Exception("Can't parse date: %s" % date)


def _get_first_entry(path):
    entries = list(sorted(os.listdir(path)))
    for e in entries:
        if e[0] != '.':
            return e
    return None


def _get_ordered_entries(path):
    return list(
            sorted(
                filter(
                    lambda i: i[0] != '.',
                    os.listdir(path)),
                key=_get_episode_key))


number_suffix_re = re.compile(r'\d+$')


def _get_episode_key(path):
    # Typically season folder are just named `Season X` with no padding,
    # so if we just order stuff naively, we'll get `Season 1`, `Season 10`,
    # `Season 11`, `Season 2`. But we obviously want proper numbered order
    # so we try to detect the number suffix.
    m = number_suffix_re.search(path)
    if m:
        start, end = m.span()
        padlen = 6 - (end - start)
        assert padlen >= 0
        pad = '0' * padlen
        return path[:start] + pad + path[start:]
    return path


def _tuples_to_dict(tuples):
    d = {}
    for k, v in tuples:
        d[k] = v
    return d


def main():
    parser = argparse.ArgumentParser(
        prog='SaturdayMorning',
        description="A little script for copying things on a schedule."
    )
    parser.add_argument('source',
                        help="The directory where to find the source files.")
    parser.add_argument('destination',
                        help="The directory to which to move relevant files.")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Show debug messages.")
    parser.add_argument('--dry-run', action='store_true',
                        help="Show what would happen, but don't move anything")
    parser.add_argument('--date',
                        help="Run as if it was the given date.")
    args = parser.parse_args()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(message)s'))
    if args.verbose:
        root_logger.setLevel(logging.DEBUG)
        handler.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    try:
        sm = SaturdayMorning(args.source, date=args.date, dry_run=args.dry_run)
        sm.run(args.destination)
    except Exception as ex:
        logger.exception(ex)
        sys.exit(1)

if __name__ == '__main__':
    main()
