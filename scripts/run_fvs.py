#!/usr/bin/env python
"""run_fvs.py

After running build_keys ....

run_fvs.py plots/varWC_rx1...../  <--- this is a plot directory containing .key files to be run

Usage:
    run_fvs.py PLOTDIRECTORY
    run_fvs.py (-h | --help)
    run_fvs.py --version

Options:
    -h --help     Show this screen.
    --version     Show version.
"""
from docopt import docopt
import os
import glob
from shutil import copytree, rmtree, copyfile
from subprocess import Popen, PIPE
import gzip
import errno
import time

try:
    from extract import extract_data
    import sqlite3
    from pandas.io import sql as sqlio
except ImportError:
    # pandas is probably not available
    print "\t WARNING: Unable to extract data from .out file. Import failed, installing pandas should fix."
    extract_data = None


class FVSError(Exception):
    pass


def prep_final(plotdir, extract_methods):
    final = os.path.abspath(os.path.join(plotdir, "..", "..", "final"))
    if not os.path.exists(final):
        try:
            os.makedirs(final)
        except OSError as exc:
            # For thread saftey
            if exc.errno == errno.EEXIST and os.path.isdir(final):
                pass

    if 'sqlite3' in extract_methods:
        db_path = os.path.join(final, "data.db")
        try:
            create_data_db(db_path)
        except sqlite3.OperationalError as e:
            if e.message == "table trees_fvsaggregate already exists":
                # table already exists
                # TODO ... check for table rather than try/except?
                pass
            else:
                raise sqlite3.OperationalError(e.message)

    return final


def write_final(dirname, work, final, extract_methods):
    df = extract_data(work)

    if 'csv' in extract_methods:
        csv = os.path.join(final, dirname + ".csv")
        df.to_csv(csv, index=False, header=True)
        print "\tSUCCESS: Extracted data from .out file. CSV written to ./final/%s.csv" % dirname

    if 'sqlite3' in extract_methods:
        db_path = os.path.join(final, "data.db")
        conn = sqlite3.connect(db_path, timeout=10)  # 10 seconds to avoid write deadlock?
        try:
            sqlio.write_frame(df, name='trees_fvsaggregate',
                con=conn, flavor='sqlite', if_exists='append')
        except sqlite3.IntegrityError as e:
            if e.message.endswith("are not unique"):
                # try to drop and rerun
                cursor = conn.cursor()

                delete_sql = """DELETE FROM trees_fvsaggregate
                  WHERE var = '%(var)s'
                  AND rx = %(rx)d
                  AND cond = %(cond)d
                  AND site = %(site)d
                  AND climate = '%(climate)s'
                """ % df.irow(0)  # assume the dataframe has the same data

                res = cursor.execute(delete_sql)
                if res.rowcount > 0:
                    print "\tNOTICE : Deleting %d old rows from ./final/data.db" % res.rowcount

                # try again
                sqlio.write_frame(df, name='trees_fvsaggregate',
                    con=conn, flavor='sqlite', if_exists='append')

            else:
                # something else went wrong
                conn.rollback()
                raise sqlite3.IntegrityError(e.message)

        conn.commit()
        conn.close()
        print "\tSUCCESS: Extracted data from .out file. Row appended to ./final/data.db"


def apply_fvs_to_plotdir(plotdir, extract_methods=None):
    """
    from plots/varWC_rx1_cond31566, 
        write working dir to ../../work/varWC_rx1_cond31566
    """
    start = time.time()

    assert os.path.exists(plotdir)
    path = os.path.normpath(plotdir)
    dirname = path.split(os.sep)[-1]

    if not extract_methods:
        # default to both
        extract_methods = ['sqlite3', 'csv']
    
    final = prep_final(plotdir, extract_methods)

    outfiledir = os.path.join(final, "out")
    if not os.path.exists(outfiledir):
        try:
            os.makedirs(outfiledir)
        except OSError as exc:
            # For thread saftey
            if exc.errno == errno.EEXIST and os.path.isdir(final):
                pass

    work_base = os.path.abspath(os.path.join(plotdir, "..", "..", "work"))
    if not os.path.exists(work_base):
        try:
            os.makedirs(work_base)
        except OSError as exc:
            # For thread saftey
            if exc.errno == errno.EEXIST and os.path.isdir(final):
                pass
    work = os.path.join(work_base, dirname)
    if os.path.exists(work):
        rmtree(work)
    copytree(plotdir, work)

    keys = glob.glob(os.path.join(work, '*.key'))
    for key in keys:
        try:
            fvsout, fvswarn = execute_fvs(key)
            if fvsout:
              print fvsout

            warnfile = os.path.join(final, "out", os.path.basename(key).replace(".key", ".warn"))
            with open(warnfile, 'w') as fh:
                fh.write(fvswarn)
            print "\tWARNING: fvs warnings written to ./final/out/%s" % \
                  os.path.basename(key).replace(".key", ".warn")
        except Exception as exc:
            outfile = key.replace(".key", ".out")
            print "\tFVS failed. OUT file at ./final/out/%s" % os.path.basename(outfile)
            copyfile(outfile, os.path.join(outfiledir, os.path.basename(outfile)))

            err = os.path.join(final, dirname + ".err")
            with open(err, 'w') as fh:
                fh.write("key:\n" + key + "\n" + exc.message)
            print "\tERROR written to ./final/%s.err" % dirname

            # leave work dir around after failure, just delete the big old .trl files
            trls = glob.glob(os.path.join(work, '*.trl'))
            for trl in trls:
                os.remove(trl)

            return False

    # automatically write outfiles
    outs = glob.glob(os.path.join(work, '*.out'))
    for fvsworkfile in outs:
        outpath = os.path.join(outfiledir, os.path.basename(fvsworkfile) + ".gz")
        with gzip.open(outpath, 'wb') as outfh:
            with open(fvsworkfile, 'r') as infh:
                outfh.write(infh.read())
    print "\tSUCCESS: All offsets completed. GZipped FVS .out files in ./final/out/"

    # If we've got svs files, save 'em uncompressed (TODO might want to compress these?)
    svss = glob.glob(os.path.join(work, '*.svs'))
    svsfiledir = os.path.join(final, "svs")
    for svs in svss:
        if not os.path.exists(svsfiledir):
            try:
                os.makedirs(svsfiledir)
            except OSError as exc:
                # For thread saftey
                if exc.errno == errno.EEXIST and os.path.isdir(final):
                    pass
        copyfile(svs, os.path.join(svsfiledir, os.path.basename(svs)))

    try:
        write_final(dirname, work, final, extract_methods)
    except Exception as exc:
        err = os.path.join(final, dirname + ".err")
        with open(err, 'w') as fh:
            fh.write(exc.message)
        print "\tERROR in write_final; written to ./final/%s.err" % dirname

    # If we've gotten this far, we don't need the work directory any longer
    try:
        rmtree(work)
    except:
        print "\tNOTICE : unable to delete work directory"

    elapsed = time.time() - start
    with open(os.path.join(final, "timer.csv"), 'a') as fh:
        fh.write("%s,%f\n" % (os.path.basename(plotdir).replace('_', ','), elapsed))

    return True


def execute_fvs(key):
    basename = os.path.basename(key)
    prefix, ext = os.path.splitext(basename)

    assert basename[0:3] == "var"
    variant = basename[3:5].lower()
    
    if os.name == 'posix':
        fvsbin_dir = '/usr/local/bin'
        extension = 'c'  # open-fvs added c to end, e.g. FVSpnc
    elif os.name == 'nt':
        fvsbin_dir = 'C:\\FVSbin'
        extension = ".exe"
    fvsbin = os.path.join(fvsbin_dir, 'FVS%s' % variant + extension)

    cmd = [fvsbin, '--keywordfile=%s' % basename]
    print ' '.join(cmd)

    os.chdir(os.path.dirname(key))
    if os.name == 'posix': 
        proc = Popen(cmd, shell=False, stdout=PIPE, stderr=PIPE)
    elif os.name == 'nt':
        # Windows process handling is a bit screwy
        from subprocess import CREATE_NEW_PROCESS_GROUP
        proc = Popen(cmd, shell=False, stdout=PIPE, stderr=PIPE, creationflags=CREATE_NEW_PROCESS_GROUP)
    (fvsout, fvserr) = proc.communicate() 
    returncode = proc.returncode
    
    # Assume STOP 10 is OK if there are no errors in the .out file
    if 'STOP 10' in fvserr:
        fvserr = ''
        fvswarn = fvserr
    if returncode not in [0, 10]:
        fvserr += "PROCESS RETURNED CODE %d" % returncode

    if os.name == 'nt':
        # Windows process handling is a bit screwy (part 2)
        os.chdir("..")  # otherwise process holds onto work dir
        import signal
        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)

    # Validate outputs
    outfile = key.replace(".key", ".out")
    if not os.path.exists(outfile):
        fvserr += "No OUT file\n"
    if not os.path.exists(key.replace(".key", ".trl")):
        fvserr += "No TRL file\n"

    # Validate .out file
    still_capturing_error = 0
    still_capturing_warning = 0
    fvswarn = ""
    with open(outfile, 'r') as fh:
        for line in fh.readlines():
            if still_capturing_error > 0:
                fvserr += line
                still_capturing_error -= 1

            if still_capturing_warning > 0:
                fvswarn += line
                still_capturing_warning -= 1

            if "NO CLIMATE DATA FOR THIS STAND" in line:
                fvserr += line
                still_capturing_error = 0

            elif "ERROR" in line:
                if line.startswith("RATIO OF STANDARD ERRORS"):
                    continue
                # We've found a actual error, grab the next few lines
                fvserr += line
                still_capturing_error = 3

            elif "WARNING" in line:
                fvswarn += line
                # We've found a warning grab the next few lines
                still_capturing_warning = 3

    if fvserr:
        raise FVSError(fvserr)

    return fvsout, fvswarn

def create_data_db(db_path):

    if not sqlite3:
        raise Exception('Install sqlite3 to use create_table_db')

    conn = sqlite3.connect(db_path)

    create_sql = """CREATE TABLE trees_fvsaggregate (
      "accretion" INTEGER, -- int64
      "after_ba" INTEGER, -- int64
      "after_merch_bdft" INTEGER, -- int64
      "after_merch_ft3" INTEGER, -- int64
      "after_qmd" REAL, -- float64
      "after_sdi" INTEGER, -- int64
      "after_total_ft3" INTEGER, -- int64
      "after_tpa" INTEGER, -- int64
      "age" INTEGER, -- int64
      "climate" TEXT, -- object
      "cond" INTEGER, -- int64
      "fortype" INTEGER, -- int64
      "mortality" INTEGER, -- int64
      "offset" INTEGER, -- int64
      "removed_merch_bdft" INTEGER, -- int64
      "removed_merch_ft3" INTEGER, -- int64
      "removed_total_ft3" INTEGER, -- int64
      "removed_tpa" INTEGER, -- int64
      "rx" INTEGER, -- int64
      "site" INTEGER, -- int64
      "size_class" INTEGER, -- int64
      "start_ba" INTEGER, -- int64
      "start_merch_bdft" INTEGER, -- int64
      "start_merch_ft3" INTEGER, -- int64
      "start_total_ft3" INTEGER, -- int64
      "start_tpa" INTEGER, -- int64
      "stocking_class" INTEGER, -- int64
      "var" TEXT, -- object
      "year" INTEGER, -- int64
      "CEDR_BF" REAL, -- float64
      "CEDR_HRV" REAL, -- float64
      "CH_CF" REAL, -- float64
      "CH_HW" REAL, -- float64
      "CH_TPA" REAL, -- float64
      "CUT_TYPE" REAL, -- float64
      "DEFOL" REAL, -- object
      "DF_BF" REAL, -- float64
      "DF_BTL" REAL, -- object
      "DF_HRV" REAL, -- float64
      "ES_BTL" REAL, -- float64
      "FIREHZD" REAL, -- float64
      "HW_BF" REAL, -- float64
      "HW_HRV" REAL, -- float64
      "LG_CF" REAL, -- float64
      "LG_HW" REAL, -- float64
      "LG_TPA" REAL, -- float64
      "MNCONBF" REAL, -- float64
      "MNCONHRV" REAL, -- float64
      "MNHW_BF" REAL, -- float64
      "MNHW_HRV" REAL, -- float64
      "NSODIS" REAL, -- float64
      "NSOFRG" REAL, -- float64
      "NSONEST" REAL, -- float64
      "PINEBTL" REAL, -- object
      "PINE_BF" REAL, -- float64
      "PINE_HRV" REAL, -- float64
      "PLANT" REAL, -- float64
      "SM_CF" REAL, -- float64
      "SM_HW" REAL, -- float64
      "SM_TPA" REAL, -- float64
      "SPPRICH" REAL, -- float64
      "SPPSIMP" REAL, -- float64
      "SPRC_BF" REAL, -- float64
      "SPRC_HRV" REAL, -- float64
      "WJ_BF" REAL, -- float64
      "WJ_HRV" REAL, -- float64
      "WW_BF" REAL, -- float64
      "WW_HRV" REAL, -- float64
      "merch_carbon_removed" REAL, -- float64
      "merch_carbon_stored" REAL, -- float64
      "agl" REAL, -- float64
      "bgl" REAL, -- float64
      "calc_carbon" REAL, -- float64
      "dead" REAL, -- float64
      "total_stand_carbon" REAL, -- float64
      "econ_removed_merch_bdft" REAL, -- float64
      "econ_removed_merch_ft3" REAL, -- float64
      "undiscounted_revenue" REAL, -- float64
      "harvest_report" TEXT, -- object

      -- if primary keys change, make sure to update IntegrityError logic above
      PRIMARY KEY ("var", "rx", "cond", "site", "climate", "offset", "year")
    );"""

    cursor = conn.cursor()
    cursor.execute(create_sql)

    idx_sqls = [
        "CREATE INDEX idx_trees_fvsaggregate_var ON trees_fvsaggregate (var);",
        "CREATE INDEX idx_trees_fvsaggregate_year ON trees_fvsaggregate (year);",
        "CREATE INDEX idx_trees_fvsaggregate_cond ON trees_fvsaggregate (cond);",
        "CREATE INDEX idx_trees_fvsaggregate_rx ON trees_fvsaggregate (rx);",
        "CREATE INDEX idx_trees_fvsaggregate_climate ON trees_fvsaggregate (climate);",
        'CREATE INDEX idx_trees_fvsaggregate_offset ON trees_fvsaggregate ("offset");',
        'CREATE INDEX idx_fvs ON trees_fvsaggregate ("var", "rx", "cond", "site", "climate", "offset");'
    ]
    for sql in idx_sqls:
        cursor.execute(sql)

    conn.commit()
    conn.close()
    return

if __name__ == "__main__":
    args = docopt(__doc__, version='2.0')

    indata = args['PLOTDIRECTORY']
    apply_fvs_to_plotdir(indata)
