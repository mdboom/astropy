# TODO: this file should be refactored to use a more thread-safe and
# race-condition-safe lockfile mechanism.

import os
import re
import sys
import stat
import datetime

from ...extern.six.moves.urllib.request import urlopen
from ...extern.six.moves import xmlrpc_client as xmlrpc
from ...extern import six

from ... import log

from .constants import SSL_SUPPORT

from ...utils.data import get_readable_fileobj

if SSL_SUPPORT:
    import ssl
    SSL_EXCEPTIONS = (ssl.SSLError,)
else:
    SSL_EXCEPTIONS = ()


def read_lockfile(lockfilename):
    """
    Read in the lockfile given by ``lockfilename`` into a dictionary.
    """
    # lockfilename may be a local file or a remote URL, but
    # get_readable_fileobj takes care of this.
    lockfiledict = {}
    with get_readable_fileobj(lockfilename) as f:
        for line in f:
            if not line.startswith(b"#"):
                kw, val = line.split(b"=")
                lockfiledict[kw.decode().strip()] = val.decode().strip()
    return lockfiledict


def write_lockfile(lockfilename, lockfiledict):

    lockfile = open(lockfilename, "w")
    lockfile.close()
    os.chmod(lockfilename, stat.S_IREAD + stat.S_IWRITE)

    lockfile = open(lockfilename, "w")
    lockfile.write("# SAMP lockfile written on %s\n" % datetime.datetime.now().isoformat())
    lockfile.write("# Standard Profile required keys\n")
    for key, value in six.iteritems(lockfiledict):
        lockfile.write("{0}={1}\n".format(key, value))
    lockfile.close()


def create_lock_file(lockfilename=None, mode=None, hub_id=None, hub_params=None):

    # Remove lock-files of dead hubs
    remove_garbage_lock_files()

    lockfiledir = ""

    # CHECK FOR SAMP_HUB ENVIRONMENT VARIABLE
    if "SAMP_HUB" in os.environ:
        # For the time being I assume just the std profile supported.
        if os.environ["SAMP_HUB"].startswith("std-lockurl:"):

            lockfilename = os.environ["SAMP_HUB"][len("std-lockurl:"):]
            lockfile_parsed = urlparse.urlparse(lockfilename)

            if lockfile_parsed[0] != 'file':
                warnings.warn("Unable to start a Hub with lockfile %s. Start-up process aborted." % lockfilename, SAMPWarning)
                return False
            else:
                lockfilename = lockfile_parsed[2]
    else:

        # If it is a fresh Hub instance
        if lockfilename is None:

            log.debug("Running mode: " + mode)

            if mode == 'single':
                lockfilename = ".samp"
            else:
                lockfilename = "samp-hub-%s" % hub_id
                lockfiledir = os.path.join(os.path.expanduser('~'), ".samp-1")

            # If missing create .samp-1 directory
            if not os.path.isdir(lockfiledir):
                os.mkdir(lockfiledir)
                os.chmod(lockfiledir, stat.S_IREAD + stat.S_IWRITE + stat.S_IEXEC)

            lockfilename = os.path.join(lockfiledir, lockfilename)

        else:
            log.debug("Running mode: multiple")

    hub_is_running, lockfiledict = check_running_hub(lockfilename)

    if hub_is_running:
        warnings.warn("Another SAMP Hub is already running. Start-up process aborted.", SAMPWarning)
        return False

    log.debug("Lock-file: " + lockfilename)

    write_lockfile(lockfilename, hub_params)

    return lockfilename


def get_main_running_hub():
    """
    Get either the hub given by the environment variable SAMP_HUB, or the one
    given by the lockfile .samp in the user home directory.
    """
    hubs = get_running_hubs()

    if len(hubs.keys()) == 0:
        raise SAMPHubError("Unable to find a running SAMP Hub.")

    # CHECK FOR SAMP_HUB ENVIRONMENT VARIABLE
    if "SAMP_HUB" in os.environ:
        # For the time being I assume just the std profile supported.
        if os.environ["SAMP_HUB"].startswith("std-lockurl:"):
            lockfilename = os.environ["SAMP_HUB"][len("std-lockurl:"):]
        else:
            raise SAMPHubError("SAMP Hub profile not supported.")
    else:
        lockfilename = os.path.join(os.path.expanduser('~'), ".samp")

    return hubs[lockfilename]


def get_running_hubs():
    """
    Return a dictionary containing the lock-file contents of all the currently
    running hubs (single and/or multiple mode).

    The dictionary format is:

    ``{<lock-file>: {<token-name>: <token-string>, ...}, ...}``

    where ``{<lock-file>}`` is the lock-file name, ``{<token-name>}`` and
    ``{<token-string>}`` are the lock-file tokens (name and content).

    Returns
    -------
    running_hubs : dict
        Lock-file contents of all the currently running hubs.
    """

    hubs = {}
    lockfilename = ""

    # HUB SINGLE INSTANCE MODE

    # CHECK FOR SAMP_HUB ENVIRONMENT VARIABLE
    if "SAMP_HUB" in os.environ:
        # For the time being I assume just the std profile supported.
        if os.environ["SAMP_HUB"].startswith("std-lockurl:"):
            lockfilename = os.environ["SAMP_HUB"][len("std-lockurl:"):]
    else:
        lockfilename = os.path.join(os.path.expanduser('~'), ".samp")

    hub_is_running, lockfiledict = check_running_hub(lockfilename)

    if hub_is_running:
        hubs[lockfilename] = lockfiledict

    # HUB MULTIPLE INSTANCE MODE

    lockfiledir = ""

    lockfiledir = os.path.join(os.path.expanduser('~'), ".samp-1")

    if os.path.isdir(lockfiledir):
        for filename in os.listdir(lockfiledir):
            if filename.startswith('samp-hub'):
                lockfilename = os.path.join(lockfiledir, filename)
                hub_is_running, lockfiledict = check_running_hub(lockfilename)
                if hub_is_running:
                    hubs[lockfilename] = lockfiledict

    return hubs


def check_running_hub(lockfilename):
    """
    Test whether a hub identified by ``lockfilename`` is running or not.

    Parameters
    ----------
    lockfilename : str
        Lock-file name (path + file name) of the Hub to be tested.

    Returns
    -------
    is_running : bool
        Whether the hub is running
    hub_params : dict
        If the hub is running this contains the parameters from the lockfile
    """

    is_running = False
    lockfiledict = {}

    # Check whether a lockfile alredy exists
    try:
        lockfiledict = read_lockfile(lockfilename)
    except IOError:
        return is_running, lockfiledict

    if "samp.hub.xmlrpc.url" in lockfiledict:
        try:
            proxy = xmlrpc.ServerProxy(lockfiledict["samp.hub.xmlrpc.url"]
                                       .replace("\\", ""), allow_none=1)
            proxy.samp.hub.ping()
            is_running = True
        except xmlrpc.ProtocolError:
            # There is a protocol error (e.g. for authentication required),
            # but the server is alive
            is_running = True
        except SSL_EXCEPTIONS:
            # SSL connection refused for certifcate reasons...
            # anyway the server is alive
            is_running = True

    return is_running, lockfiledict


def remove_garbage_lock_files():

    lockfilename = ""

    # HUB SINGLE INSTANCE MODE

    lockfilename = os.path.join(os.path.expanduser('~'), ".samp")

    hub_is_running, lockfiledict = check_running_hub(lockfilename)

    if not hub_is_running:
        # If lockfilename belongs to a dead hub, then it is deleted
        if os.path.isfile(lockfilename):
            try:
                os.remove(lockfilename)
            except OSError:
                pass

    # HUB MULTIPLE INSTANCE MODE

    lockfiledir = os.path.join(os.path.expanduser('~'), ".samp-1")

    if os.path.isdir(lockfiledir):
        for filename in os.listdir(lockfiledir):
            if filename.startswith('samp-hub'):
                lockfilename = os.path.join(lockfiledir, filename)
                hub_is_running, lockfiledict = check_running_hub(lockfilename)
                if not hub_is_running:
                    # If lockfilename belongs to a dead hub, then it is deleted
                    if os.path.isfile(lockfilename):
                        try:
                            os.remove(lockfilename)
                        except OSError:
                            pass